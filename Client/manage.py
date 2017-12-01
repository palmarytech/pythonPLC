# coding=utf-8
import os
import argparse
import subprocess

# 命令行选项
parser = argparse.ArgumentParser()
parser.add_argument('--reset', action='store_true')
parser.add_argument('--start', action='store_true')
parser.add_argument('--clean-beat', action='store_true')
parser.add_argument('--config')
parser.add_argument('--url')
args = parser.parse_args()

os.environ['env'] = 'dev'
os.environ['url'] = 'dev-server'

if args.config == 'prod':
    os.environ['env'] = 'prod'

if args.url == 'server':
    os.environ['url'] = 'server'

from app import boot, database_reset, app, get_config, before_running
from param import cf, here
from models import Session

python_path = cf.get(os.environ.get('env'), 'python')

if args.reset:
    database_reset()

if args.clean_beat:
    subprocess.call('celery purge -A app -f', shell=True)

if args.start:
    # 清空上次运行的残留数据
    subprocess.call('celery purge -A app -f', shell=True)

    Session.close_all()

    if os.path.exists(here + '/celerybeat-schedule'):
        delete_schedule = subprocess.call('rm {}/celerybeat-schedule'.format(here), shell=True)

    boot()

    get_config()

    before_running()

    # 启动flower
    flower = subprocess.Popen('{}flower --broker="{}"'.format(python_path, app.conf['broker_url']), shell=True)

    # 启动celery beat worker
    celery = subprocess.call('{}celery -B -A app worker -l warn -E --autoscale=8,4'.format(python_path), shell=True)

    # 关闭flower
    flower.kill()
