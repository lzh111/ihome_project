## 运行项目注意事项

#### 1、settings中的数据库配置，要改成自己的ip和密码
#### 2、redis的ip和端口需要配置，并且确定启动redis

#### 3、数据库备份sql脚本放在script目录下面
```python
mysql -h ip地址 -u root -p ihome < ihome.sql(路径)
```
#### 4、将整个数据库备份到你的数据库后，将模型类拷贝，不需要做迁移
#### 5、migrations下的文件不要删除
#### 6、进入虚拟环境，并且安装requirements.txt, 在script目录下
```python
pip install -r requirements.txt
```
#### 7、自己添加房屋的时候，最好用静态文件夹中的图片

#### 8、项目代码打TODO的地方，可以进行优化
#### 9、其他地方有优化的可以联系我 18511551140


