# coding=utf-8
import os
import base64
import hmac
import json
import random
import zlib

import MySQLdb
import eventlet
from celery import Celery
from flask import Flask, request, jsonify, g, render_template, redirect, url_for, current_app, flash, Config
from flask_login import login_user, user_logged_in
from flask_socketio import SocketIO
from pandas.io.sql import read_sql

from models import *
from ext import mako, hashing, api, admin, login_manager, csrf, cache, debug_toolbar
from forms import RegistrationForm

from rest.api_plc import PLCResource
from rest.api_station import StationResource
from rest.api_group import GroupResource
from rest.api_variable import VariableResource

from admin import CustomView, CustomModelView, CustomFileAdmin

eventlet.monkey_patch()

app = Flask(__name__, template_folder='templates')
here = os.path.abspath(os.path.dirname(__file__))
app.config.from_pyfile(os.path.join(here, 'config_dev/config.py'))
app.config.from_pyfile(os.path.join(here, 'config_dev/celeryconfig.py'))

mako.init_app(app)
db.init_app(app)
hashing.init_app(app)
admin.init_app(app)
login_manager.init_app(app)
# csrf.init_app(app)
debug_toolbar.init_app(app)
cache.init_app(app)

SOCKETIO_REDIS_URL = app.config['CELERY_RESULT_BACKEND']
socketio = SocketIO(
    app, async_mode='eventlet',
    message_queue=SOCKETIO_REDIS_URL
)

celery = Celery(app.name)
celery.conf.update(app.config)

api.add_resource(StationResource, '/api/station/<name>')
api.add_resource(PLCResource, '/api/plc/<id>', '/api/plc', endpoint='api')
api.add_resource(GroupResource, '/api/group/<name>')
api.add_resource(VariableResource, '/api/variable/<name>')
api.init_app(app)

admin.add_view(CustomView(name='Custom'))
models = [YjStationInfo, YjPLCInfo, YjGroupInfo, YjVariableInfo, Value, TransferLog, User]

for model in models:
    admin.add_view(
        CustomModelView(model, db.session,
                        category='models')
    )
admin.add_view(CustomFileAdmin(os.path.join(os.path.dirname(__file__), 'static'),
                               '/static/',
                               name='Static File'))


def value2dict(std):
    return {
        "id": std.id,
        "variable_id": std.variable_id,
        "value": std.value
    }


def get_current_user():
    users = User.query.all()
    return random.choice(users)


def encryption(data):
    """
    :param data: dict
    :return: dict
    """

    h = hmac.new(b'poree')
    data = unicode(data)
    # data = base64.b64encode(data)
    h.update(bytes(data))
    data = zlib.compress(data)
    data = base64.b64encode(data)
    digest = h.hexdigest()
    data = {"data": data, "digest": digest}
    return data


def decryption(rj):
    """
    :param rj: json
    :return: dict
    """

    data = rj['data']
    di = rj['digest']
    data = base64.b64decode(data)
    data = zlib.decompress(data)
    h = hmac.new(b'poree')
    h.update(bytes(data))
    test = h.hexdigest()
    if di == test:
        # data = base64.b64decode(data)
        data = json.loads(data.replace("'", '"'))
    else:
        data = {"status": "Error"}
    return data


def get_data_from_query(models):
    # 输入session.query()查询到的模型实例列表,读取每个实例每个值,放入列表返回
    data_list = []
    for model in models:
            model_column = {}
            for c in model.__table__.columns:
                model_column[c.name] = str(getattr(model, c.name, None))
            data_list.append(model_column)
    return data_list


def get_data_from_model(model):
    # 读取一个模型实例中的每一项与值，放入字典
    model_column ={}
    for c in model.__table__.columns:
        model_column[c.name] = str(getattr(model, c.name, None))
    return model_column


@app.before_first_request
def setup():
    # db.drop_all()
    # db.create_all()
    # fake_users = [
    #     User('xiaoming', '3'),
    #     User('wangzhe', '2'),
    #     User('admin', '1')
    # ]
    # db.session.add_all(fake_users)
    # db.session.commit()
    pass


@app.before_request
def before_request():
    g.user = get_current_user()


@app.teardown_appcontext
def teardown(exc=None):
    if exc is None:
        db.session.commit()
    else:
        db.session.rollback()
    db.session.remove()
    g.user = None


@app.context_processor
def template_extras():
    return {'enumerate': enumerate, 'current_user': g.user}


@app.template_filter('capitalize')
def reverse_filter(s):
    return s.capitalize()


@celery.task
def station_check():
    with app.app_context():
        current_time = datetime.datetime.now()
        stations = db.session.query(YjStationInfo)
        for s in stations:
            s_log = TransferLog.query.filter_by(idnum=s.idnum).order_by(TransferLog.time.desc()).first()
            if s_log:
                last_time = s_log.time
                last_level = s_log.level
                if (current_time - last_time).seconds > 5 and (current_time - last_time).days == 0:
                    warn_level = last_level + 1
                    if warn_level > 2:
                        warn = TransferLog(id_num=s.idnum, level=3, time=current_time, note='ERROR')
                    else:
                        warn = TransferLog(id_num=s.idnum, level=last_level + 1, time=current_time, note='WARNING')
                else:
                    warn = TransferLog(id_num=s.idnum, level=0, time=current_time, note='OK')
            else:
                warn = TransferLog(id_num=s.idnum, level=0, time=current_time, note='OK')
            db.session.add(warn)
            db.session.commit()


@user_logged_in.connect_via(app)
def _track_logins(sender, user, **extra):
    # 记录用户登录次数，登录IP
    user.login_count += 1
    user.last_login_ip = request.remote_addr
    db.session.add(user)
    db.session.commit()


# @login_manager.user_loader
# def load_user(userid):
#     from models import User
#     return User.query.get(userid)

# @login_manager.user_loader
# def user_loader(id):
#     user = User.query.filter_by(id=id).first()
#     return user


@app.route('/', methods=['GET', 'POST'])
@cache.cached(timeout=60)
def index():
    if request.method == 'POST':
        data = request.get_json(force=True)
        # data = decryption(rv)
        uploaded_data = YjPLCInfo.query.filter_by(id=data["id"]).first()
        if uploaded_data:
            uploaded_data = YjPLCInfo.query.all()
            return render_template('index_post.html', uploaded_data=uploaded_data)
        else:
            uploaded_data = YjPLCInfo(name=data["name"])
            # todo 当输入值的键不存在时,怎么使用默认值代替
        db.session.add(uploaded_data)
        db.session.commit()
        uploaded_data = YjPLCInfo.query.all()
        return render_template('index_post.html', uploaded_data=uploaded_data)
    users = User.query.all()
    return render_template('index.html', users=users)


@app.route('/register', methods=['GET', 'POST'])
@csrf.exempt
def register():
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User(name=form.name.data, email=form.email.data, password=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('registering successed!')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    if request.method == 'GET':
        return '''
<form action='login' method='POST'>
    <input type='text' name='name' id='name' placeholder='name'></input>
    <input type='password' name='pw' id='pw' placeholder='password'></input>
    <input type='submit' name='submit'></input>
</form>
        '''

    name = request.form.get('name')
    password = request.form.get('pw')
    user = User.query.filter_by(name=name).first()

    if not user:
        return 'user is not exist'
    if user.check_password(password):
        login_user(user)
        return redirect(url_for('index'))
    return 'password error'


@app.route('/beats', methods=['GET', 'POST'])
def beats():
    data = request.get_json(force=True)
    # data = decryption(rv)

    station = YjStationInfo.query.filter_by(idnum=data["idnum"]).first()
    station.con_date = datetime.datetime.now()
    db.session.add(station)
    db.session.commit()

    if station.version != data["version"]:
        station.modification = 1

    data = {"modification": station.modification, "status": "OK"}
    # data = encryption(data)
    return jsonify(data)


@app.route('/config', methods=['GET', 'POST'])
def set_config():

    if request.method == 'POST':
        data = request.get_json(force=True)

        # 将本次发送过配置的站点数据表设置为无更新
        db.session.query(YjStationInfo).filter(YjStationInfo.idnum == data["idnum"]).update({YjStationInfo.modification: 0})
        # data = decryption(data)

        # 读取staion表数据,根据外链,读出该station下的plc、group variable的数据.每一项数据为一个字典,每个表中所有数据存为一个列表.
        config_station = YjStationInfo.query.filter_by(idnum=data["idnum"]).first()

        station_config = get_data_from_model(config_station)

        plcs_config = []
        groups_config = []
        variables_config = []

        for plc in config_station.plcs.all():
            plc_config = get_data_from_model(plc)

            plcs_config.append(plc_config)

            groups = plc.groups.all()
            groups_config += get_data_from_query(groups)

            variables = plc.variables.all()
            variables_config += get_data_from_query(variables)

        # 包装数据
        data = {"YjStationInfo": station_config, "YjPLCInfo": plcs_config,
                "YjGroupInfo": groups_config, "YjVariableInfo": variables_config,
                "status": "OK"}

        # data = encryption(data)
        return jsonify(data)


@app.route('/upload', methods=['POST'])
def upload():
    if request.method == 'POST':
        data = request.get_json(force=True)
        # data = decryption(data)

        # 验证上传数据
        station = data["station"]
        version = data["version"]

        # 查询服务器是否有正在上传的站信息
        station_now = YjStationInfo.query.filter_by(idnum=station).first_or_404()

        # 查询上传信息的版本是否匹配
        try:
            assert(station_now.version == version)
        except AssertionError:
            return jsonify({"status": "Version Error"})

        for v in data["Value"]:
            upload_data = Value(variable_name=v["variable_name"], value=v["value"], get_time=v["get_time"])
            db.session.add(upload_data)
        db.session.commit()

        values = data["Value"]

        return jsonify({"input": [v for v in values],
                        "status": "OK",
                        "station": station,
                        "version": version})


def _get_frame(date_string):
    db = MySQLdb.connect('localhost', 'web', 'web', 'pyplc')
    query = 'SELECT * FROM {}'.format(date_string)
    df = read_sql(query, db)
    df = df.head(100)
    return df


@app.route('/db/<any(yjstationinfo, yjplcinfo, yjgroupinfo, yjvariableinfo):date_string>/')
@cache.cached(timeout=10)
def show_tables(date_string=None):
    df = _get_frame(date_string)
    if isinstance(df, bool) and not df:
        return 'Bad data format!'
    return render_template('show_data.html', df=df.to_html(classes='frame'), date_string=date_string)


@app.route('/api/configuration/', methods=["GET", "POST"])
def give_config(*args, **kwargs):
    # data = request.get_json(force=True)

    station_config = {}
    plcs_config = []
    groups_config = []
    variables_config = []

    # config_station = YjStationInfo.query.filter_by(idnum=data["station_id"]).first()
    config_station = YjStationInfo.query.filter_by(id=1).first()
    if config_station:
        station_config = get_data_from_model(config_station)
    
        plcs = config_station.plcs.all()
        if plcs:
            for plc in plcs:
                plc_config = get_data_from_model(plc)

                plcs_config.append(plc_config)

                groups = plc.groups.all()
                if groups:
                    groups_config += get_data_from_query(groups)

                variables = plc.variables.all()
                if variables:
                    variables_config += get_data_from_query(variables)

    # 包装数据
    data = {"YjStationInfo": station_config, "YjPLCInfo": plcs_config,
            "YjGroupInfo": groups_config, "YjVariableInfo": variables_config,
            "status": "OK"}
    
    # data = encryption(data)
    return jsonify(data)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=11000, debug=True)
