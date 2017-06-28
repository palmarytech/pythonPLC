# coding=utf-8
from flask import abort, jsonify
from flask_restful import reqparse, Resource, marshal_with, fields

from web_server.models import *
from web_server.rest.parsers import station_parser, station_put_parser
from api_templete import ApiResource
from err import err_not_found
from response import rp_create, rp_delete, rp_modify


station_field = {
    'name': fields.String,
    'mac': fields.String,
    'ip': fields.String,
    'note': fields.String,
    'id_num': fields.String,
    'plc_count': fields.Integer,
    'ten_id': fields.String,
    'item_id': fields.String
}


class StationResource(ApiResource):
    def __init__(self):
        super(StationResource, self).__init__()
        self.args = station_parser.parse_args()

    def search(self, station_id):
        if not station_id:
            station_id = self.args['id']

        station_name = self.args['station_name']

        page = self.args['page']
        per_page = self.args['per_page'] if self.args['per_page'] else 10

        query = YjStationInfo.query

        if station_id:
            query = query.filter_by(id=station_id)

        if station_name:
            query = query.filter_by(name=station_name)

        if page:
            query = query.paginate(page, per_page, False).items
        else:
            query = query.all()

        return query

    def information(self, models):
        if not models:
            return err_not_found()

        info = []
        for m in models:
            data = dict()
            data['id'] = m.id
            data['station_name'] = m.name
            data['mac'] = m.mac
            data['ip'] = m.ip
            data['note'] = m.note
            data['id_num'] = m.id_num
            data['plc_count'] = m.plc_count
            data['ten_id'] = m.ten_id
            data['item_id'] = m.item_id
            data['modification'] = m.modification

            info.append(data)

        response = jsonify({'ok': 1, "data": info})
        response.status_code = 200

        return response

    def put(self, station_id=None):
        args = station_put_parser.parse_args()

        if not station_id:
            station_id = args['id']

        if station_id:
            station = YjStationInfo.query.get(station_id)

            if not station:
                return err_not_found()

            if args['name']:
                station.name = args['name']

            if args['mac']:
                station.mac = args['mac']

            if args['ip']:
                station.ip = args['mac']

            if args['note']:
                station.note = args['note']

            if args['id_num']:
                station.id_num = args['id_num']

            if args['plc_count']:
                station.plc_count = args['plc_count']

            if args['ten_id']:
                station.ten_id = args['plc_count']

            if args['item_id']:
                station.item_id = args['item_id']

            if args['modification']:
                station.modification = args['modification']

            db.session.add(station)
            db.session.commit()
            return rp_modify()

        else:
            station = YjStationInfo(name=args['name'], mac=args['mac'], ip=args['ip'], note=args['note'],
                                    id_num=args['id_num'], plc_count=args['plc_count'], ten_id=args['ten_id'],
                                    item_id=args['item_id'], modification=args['modification'])
            db.session.add(station)
            db.session.commit()
            return rp_create()
