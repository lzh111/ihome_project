import datetime

from django import http
from django.core.paginator import Paginator
from django.utils.decorators import method_decorator
from django.views import View
from django.db import DatabaseError
from django.core.cache import cache
from django.db import transaction
from django.conf import settings
from django_redis import get_redis_connection

from homes.models import Area, House, Facility, HouseImage
from libs.qiniuyun.qiniu_storage import storage
from order.models import Order
from utils import constants
from utils.decorators import login_required
from utils.param_checking import image_file
from utils.response_code import RET
import logging
import json

logger = logging.getLogger("django")


class AreaView(View):
    """
    查询地址信息
    """
    def get(self, request):

        areas_list = cache.get('area_info')

        if not areas_list:
            try:
                areas = Area.objects.all()
            except DatabaseError as e:
                logger.error(e)
                return http.JsonResponse({"errno": RET.DBERR, "errmsg": "数据库查询失败"})

            areas_list = [area.to_dict() for area in areas]

            cache.set('area_info', areas_list, 3600)

        return http.JsonResponse({"errno": RET.OK, "errmsg": "获取成功", "data": areas_list})


class HouseView(View):
    """
    发布房源
    """
    def get(self, request):
        # 获取所有的参数
        # TODO 注意这里有缓存，那么我们应该在用户添加房源的逻辑里面去删除缓存。这个逻辑我没写
        args = request.GET
        area_id = args.get('aid', '')
        start_date_str = args.get('sd', '')
        end_date_str = args.get('ed', '')
        # booking(订单量), price-inc(低到高), price-des(高到低),
        sort_key = args.get('sk', 'new')
        page = args.get('p', '1')

        try:
            page = int(page)
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        redis_conn = get_redis_connection("house_cache")
        try:
            redis_key = "houses_%s_%s_%s_%s" % (area_id, start_date_str, end_date_str, sort_key)
            data = redis_conn.hget(redis_key, page)
            if data:
                return http.JsonResponse({"errno": RET.OK, "errmsg": "OK", "data": json.loads(data)})
        except Exception as e:
            logger.error(e)

        # 对日期进行相关处理
        try:
            start_date = None
            end_date = None
            if start_date_str:
                start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
            if end_date_str:
                end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
            # 如果开始时间大于或者等于结束时间,就报错
            if start_date and end_date:
                assert start_date < end_date, Exception('开始时间大于结束时间')
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        filters = {}

        # 如果区域id存在
        if area_id:
            filters["area_id"] = area_id

        # 定义数组保存冲突的订单
        if start_date and end_date:
            # 如果订单的开始时间 < 结束时间 and 订单的结束时间 > 开始时间
            conflict_order = Order.objects.filter(begin_date__lt=end_date, end_date__gt=start_date)
        elif start_date:
            # 订单的结束时间 > 开始时间
            conflict_order = Order.objects.filter(end_date__gt=start_date)
        elif end_date:
            # 订单的开始时间 < 结束时间
            conflict_order = Order.objects.filter(begin_date__lt=end_date)
        else:
            conflict_order = []

        # 取到冲突订单的房屋id
        conflict_house_id = [order.house_id for order in conflict_order]
        # 添加条件:查询出来的房屋不包括冲突订单中的房屋id
        # TODO：不在列表中未处理，先用in来代替下
        if conflict_house_id:
            filters["id__in"] = conflict_house_id

        # 查询数据
        if sort_key == "booking":
            # 订单量从高到低
            houses_query = House.objects.filter(**filters).order_by("-order_count")
        elif sort_key == "price-inc":
            # 价格从低到高
            houses_query = House.objects.filter(**filters).order_by("price")
        elif sort_key == "price-des":
            # 价格从高到低
            houses_query = House.objects.filter(**filters).order_by("-price")
        else:
            # 默认以最新的排序
            houses_query = House.objects.filter(**filters).order_by("-create_time")

        paginator = Paginator(houses_query, constants.HOUSE_LIST_PAGE_CAPACITY)
        # 获取当前页对象
        page_houses = paginator.page(page)
        # 获取总页数
        total_page = paginator.num_pages

        houses = [house.to_basic_dict() for house in page_houses]

        data = {
            "total_page": total_page,
            "houses": houses
        }

        if page <= total_page:
            try:
                # 生成缓存用的key
                redis_key = "houses_%s_%s_%s_%s" % (area_id, start_date_str, end_date_str, sort_key)
                # 获取 redis_store 的 pipeline 对象,其可以一次可以做多个redis操作
                pl = redis_conn.pipeline()
                # 开启事务
                pl.multi()
                # 缓存数据
                pl.hset(redis_key, page, json.dumps(data))
                # 设置保存数据的有效期
                pl.expire(redis_key, constants.HOUSE_LIST_REDIS_EXPIRES)
                # 提交事务
                pl.execute()
            except Exception as e:
                logger.error(e)

        return http.JsonResponse({"errno": RET.OK, "errmsg": "OK", "data": data})

    @method_decorator(login_required)
    def post(self, request):
        # 1、获取用户
        user = request.user
        # 2、获取数据
        dict_data = json.loads(request.body.decode())
        title = dict_data.get('title')
        price = dict_data.get('price')
        address = dict_data.get('address')
        area_id = dict_data.get('area_id')
        room_count = dict_data.get('room_count')
        acreage = dict_data.get('acreage')
        unit = dict_data.get('unit')
        capacity = dict_data.get('capacity')
        beds = dict_data.get('beds')
        deposit = dict_data.get('deposit')
        min_days = dict_data.get('min_days')
        max_days = dict_data.get('max_days')

        if not all([title, price, address, area_id, room_count, acreage, unit, capacity, beds, deposit, min_days,
                    max_days]):
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        try:
            price = int(float(price) * 100)
            deposit = int(float(deposit) * 100)
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        try:
            area = Area.objects.get(id=area_id)
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.NODATA, "errmsg": "地址不存在"})

        with transaction.atomic():
            save_id = transaction.savepoint()
            # 设置数据到模型
            house = House()
            house.user = user
            house.area = area
            house.title = title
            house.price = price
            house.address = address
            house.room_count = room_count
            house.acreage = acreage
            house.unit = unit
            house.capacity = capacity
            house.beds = beds
            house.deposit = deposit
            house.min_days = min_days
            house.max_days = max_days

            try:
                house.save()
            except DatabaseError as e:
                logger.error(e)
                transaction.savepoint_rollback(save_id)
                return http.JsonResponse({"errno": RET.DBERR, "errmsg": "数据库保存失败"})

            try:
                # 设置设施信息
                facility_ids = dict_data.get('facility')
                if facility_ids:
                    facilities = Facility.objects.filter(id__in=facility_ids)
                    for facility in facilities:
                        house.facility.add(facility)
            except DatabaseError as e:
                logger.error(e)
                transaction.savepoint_rollback(save_id)
                return http.JsonResponse({"errno": RET.DBERR, "errmsg": "数据库保存失败"})

            transaction.savepoint_commit(save_id)
        return http.JsonResponse({"errno": RET.OK, "errmsg": "发布成功", "data": {'house_id': house.pk}})


class UserHouseView(View):
    """
    显示用户房源信息
    """

    @method_decorator(login_required)
    def get(self, request):

        user = request.user

        houses = [house.to_basic_dict() for house in user.houses.all()]

        return http.JsonResponse({"errno": RET.OK, "errmsg": "成功", "data": {'houses': houses}})


class HouseImageView(View):
    """
    房源图片上传
    """
    def post(self, request, house_id):
        house_image = request.FILES.get("house_image")

        if not house_image:
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        if not image_file(house_image):
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        try:
            house = House.objects.get(id=house_id)
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.NODATA, "errmsg": "该房间不存在"})

        # 读取出文件对象的二进制数据
        house_image_data = house_image.read()
        #
        try:
            # TODO:没有做异步处理
            key = storage(house_image_data)
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.THIRDERR, "errmsg": "上传图片失败"})
        with transaction.atomic():
            save_id = transaction.savepoint()
            try:
                if not house.index_image_url:
                    house.index_image_url = key
                    house.save()

                house_image = HouseImage()
                house_image.house = house
                house_image.url = key
                house_image.save()
            except Exception as e:
                logger.error(e)
                transaction.savepoint_rollback(save_id)

            transaction.savepoint_commit(save_id)

        data = {
            "url": settings.QINIU_URL + key
        }
        return http.JsonResponse({"errno": RET.OK, "errmsg": "OK", "data": data})


class HouseIndexView(View):
    """
    首页推荐房间显示
    """
    def get(self, request):

        houses_list = cache.get("house_index")
        if not houses_list:
            try:
                houses = House.objects.order_by("-order_count")[0:5]
            except Exception as e:
                logger.error(e)
                return http.JsonResponse({"errno": RET.DBERR, "errmsg": "数据库查询失败"})

            houses_list = [house.to_basic_dict() for house in houses]
            cache.set('house_index', houses_list, 3600)

        # 返回数据
        return http.JsonResponse({"errno": RET.OK, "errmsg": "OK", "data": houses_list})


class HouseDetailView(View):
    """
    房屋详情页
    """
    def get(self, request, house_id):

        try:
            house = House.objects.get(id=house_id)
        except Exception as e:
            logger.error(e)
            return http.JsonResponse({"errno": RET.PARAMERR, "errmsg": "参数错误"})

        user = request.user

        if not user.is_authenticated:
            user_id = -1
        else:
            user_id = user.id
        # 先从redis缓存中取
        redis_conn = get_redis_connection("house_cache")

        house_dict = redis_conn.get('house_info_' + house_id)
        # 如果有值,那么返回数据
        if house_dict:
            return http.JsonResponse({"errno": RET.OK, "errmsg": "OK", "data":{"user_id": user_id, "house": json.loads(house_dict)}})

        # 将数据缓存到redis中
        house_dict = house.to_full_dict()
        try:
            redis_conn.setex('house_info_' + house_id, constants.HOUSE_DETAIL_REDIS_EXPIRE_SECOND, json.dumps(house_dict))
        except Exception as e:
            logger.error(e)
        # 返回数据
        return http.JsonResponse({"errno": RET.OK, "errmsg": "OK", "data":{"user_id": user_id, "house": house_dict}})