from pprint import pprint
import functools
import time
from prettytable import PrettyTable
import requests
import json
import os
import urllib3
import subprocess
import time
import argparse

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

api_endpoints = {

    "login": "/api/auth/login",
    "labs": "/api/labs/{0}",
    "nodes": "/api/labs/{0}/nodes",
    "node": "/api/labs/{0}/nodes/{1}",
    "networks": "/api/labs/{0}/networks",
    "links": "/api/labs/{0}/links",
    "topology": "/api/labs/{0}/topology",

}


class eve_lab():
    def __init__(self, eve_lab_name, eve_ip, eve_user="admin", eve_password="eve", ):
        self.eve_lab_name = eve_lab_name

        if not self.eve_lab_name:
            print("Please provide a lab name: source /root/telco_lab.env")
            exit(1)

        self.eve_url = "https://{}".format(eve_ip)
        self.eve_user = eve_user
        self.eve_password = eve_password
        self.eve_lab_name = eve_lab_name.strip() + ".unl" if eve_lab_name.split(".")[-1] != 'unl' else eve_lab_name.strip()
        self.headers = {'Accept': 'application/json', "Content-Type": "application/json", }
        self.qemu_bin = "qemu-img"



    def update_cookies(func):
        @functools.wraps(func)
        def wrapper_decorator(self, *args, **kwargs):

            self.eve_auth_data = {
                'username': self.eve_user,
                'password': self.eve_password,
            }

            auth = requests.post(url=self.eve_url + api_endpoints["login"],
                                 headers=self.headers,
                                 verify=False,
                                 data=json.dumps(self.eve_auth_data),
                                 )

            if auth.status_code == requests.codes.ok:
                self.eve_cookies = auth.cookies
            else:
                print("Authentication failed")
                print(auth.request.url)
                print(auth.status_code)
                exit(1)
            value = func(self, *args, **kwargs)
            return value

        return wrapper_decorator

    @property
    def lab_id(self):
        return self._get(api_endpoints["labs"].format(self.eve_lab_name),
                         ["id"], format="json")[0]['id']

    @property
    def lab_home_directory(self):
        return os.path.join("/opt/unetlab/tmp/0", self.lab_id)

    def get_nodes(self, include_qcow2=True):
        all_nodes_temp = self._get(api_endpoint=api_endpoints["nodes"].format(self.eve_lab_name),
                                   fields=["name", "id", "template", "status", "image", "url", "cpu", "ram",
                                           "ethernet", "firstmac"],
                                   format="json")
        self.nodes = []
        if include_qcow2:
            for node_id in os.listdir(self.lab_home_directory):
                # TODO a bit slow, need to optimize it, may by with glob?
                node_directory = os.path.join(self.lab_home_directory, node_id)
                node_qcow2_files = [os.path.join(node_directory, f) for f in os.listdir(node_directory) if
                                    f.endswith('.qcow2')]

                # expensive operation and might overwhelm the eve server, so it's better to move processing to python instead (took 24s vs 12s)
                # node_dict = self.get(api_endpoint=api_endpoints["node"].format(self.eve_lab_name, node_id),
                #                           fields=["name", "id", "template", "status", "image", "url", "cpu", "ram",
                #                                   "ethernet", "firstmac"],
                #                           format="json")[0]
                for node in all_nodes_temp:
                    if node["id"] == int(node_id):
                        node_dict = node
                        node_dict["qcow2_files"] = node_qcow2_files
                        self.nodes.append(node_dict)
                        break
        else:
            self.nodes = all_nodes_temp

        return self.nodes

    @update_cookies
    def _get(self, api_endpoint, fields=[], format="pretty"):

        if fields:
            table = PrettyTable(fields)
            table.hrules = 1
            table.padding_width = 1
            table.horizontal_char = "-"
            table.junction_char = "+"
        _ = requests.get(url=self.eve_url + api_endpoint,
                         headers=self.headers,
                         verify=False,
                         cookies=self.eve_cookies,
                         )

        if _.status_code == requests.codes.ok:
            self.data = _.json().get('data', None)
            # pprint(self.data)
            if self.data:
                if fields:
                    if isinstance(self.data, list):
                        for index, value in enumerate(self.data):
                            table.add_row([value.get(field) for field in fields])
                    elif isinstance(self.data, dict):
                        for key, value in self.data.items():
                            if isinstance(value, dict):
                                table.add_row([value.get(field) for field in fields])
                            else:
                                # print(key,value)
                                table.add_row([self.data.get(field) for field in fields])
                                break
                else:
                    return _.json()

        else:
            print("unable to get the data")
            print(_.request.url)
            print(_.status_code)

        if fields:
            if format == "pretty":
                return table.get_string(sortby=fields[1])

            elif format == "json":
                return json.loads(table.get_json_string())[1:]

    def _filter(self, all_nodes, desired_nodes_name):
        tmp = desired_nodes_name.strip().split(",")
        final_list_of_nodes_obj = []
        for i in tmp:
            for node in all_nodes:
                if i == node["name"]:
                    final_list_of_nodes_obj.append(node)
                    break
        return final_list_of_nodes_obj

    def describe(self):

        banner = '''
                    ================================================================================
                    ******************************** {:10s} ***********************************
                    ================================================================================
        '''

        print(banner.format("lab"))
        print(self._get(api_endpoints["labs"].format(self.eve_lab_name), ["filename",
                                                                          "id",
                                                                          "description",
                                                                          "author",
                                                                          "scripttimeout"], format="pretty"))

        print(banner.format("EVE Nodes"))
        print(self._get(api_endpoints["nodes"].format(self.eve_lab_name),
                        ["name", "id", "template", "status", "image", "url", "cpu", "ram", "ethernet", "firstmac"],
                        format="pretty"))


        print(banner.format("Topology"))
        print(self._get(api_endpoints["topology"].format(self.eve_lab_name), ["source_node_name",
                                                                              "network_id",
                                                                              "source_label",
                                                                              "destination_node_name",
                                                                              "destination_label",
                                                                              "destination_interfaceId"],
                        format="pretty"))

        print(banner.format("Snapshots"))
        print(self.list_snapshots())

    def list_snapshots(self):

        nodes = self.get_nodes(include_qcow2=True)

        table = PrettyTable(["id", "name", "vm status", "snapshots", "qcow2_file"])
        table.hrules = 1
        table.padding_width = 1
        table.horizontal_char = "-"
        table.junction_char = "+"
        for node in nodes:

            for f in node["qcow2_files"]:
                command = [self.qemu_bin, "snapshot", "-l", "{}".format(f), "--force-share"]
                output_raw = subprocess.run(command, capture_output=True)
                output = subprocess.run(['awk', " NR >2 {print $2}"],
                                        input=output_raw.stdout, capture_output=True)

                if output_raw.returncode == 0:
                    table.add_row([node['id'],
                                   node["name"],
                                   "shutdown" if node["status"] == 0 else "running",
                                   output.stdout.decode("utf-8").strip(), f])
                else:
                    print("unable to execute the command: {}".format(command))
                    exit(1)
        return table.get_string(sortby="id")

    def snapshot_ops(self, snapshotname, ops="revert", nodes="all"):

        flags = {
            "revert": "-a",
            "create": "-c",
            "delete": "-d",
        }
        lab_nodes = self.get_nodes(include_qcow2=True)
        if nodes == "all":
            final_list_of_nodes = lab_nodes

        else:
            final_list_of_nodes = self._filter(all_nodes=lab_nodes, desired_nodes_name=nodes)


        for node in final_list_of_nodes:
            if node["status"] != 0:
                print("Please ensure the domain is down before working over the snapshots: '{}'".format(node["name"]))
                exit(1)

            for f in node["qcow2_files"]:
                command = [self.qemu_bin, "snapshot", flags[ops], "{}".format(snapshotname), "{}".format(f)]
                output_raw = subprocess.run(command, capture_output=True)
                if output_raw.returncode == 0:
                    print("successfully applied operation: '{}' over doamin: '{}' with snapshotname: '{}' ".format(ops,node["name"], snapshotname))
                    print(output_raw.stdout.decode("utf-8").strip())
                else:
                    print(
                        "Error on applying operation: '{}' over doamin: '{}' with snapshotname: '{}' ".format(ops,node["name"], snapshotname))
                    print(output_raw.stderr.decode("utf-8").strip())

    def nodes_ops(self, ops, nodes="all"):
        stop = 0
        lab_nodes = self.get_nodes(include_qcow2=False)

        if nodes == "all":
            final_list_of_nodes = lab_nodes

        else:
            final_list_of_nodes = self._filter(all_nodes=lab_nodes, desired_nodes_name=nodes)

        for node in final_list_of_nodes:
            print("Applying operation: {} on node: {}".format(ops, node["name"]))
            if ops == "start" and node["status"] != stop:
                print(" Node already started!")

            elif ops == "stop" and node["status"] == stop:
                print(" Node already stopped!")
            else:
                url = api_endpoints["node"].format(self.eve_lab_name, node["id"]) + "/{}".format(ops)
                if ops == "stop":
                    url = url + "/stopmode=3"  # required for eve-ng pro only
                self._get(api_endpoint=url)
                time.sleep(0.3)


if __name__ == '__main__':

    eve_ip = os.environ.get('eve_ip', None)
    eve_user = os.environ.get('eve_user', 'admin')
    eve_password = os.environ.get('eve_password', 'eve')
    eve_lab_name = os.environ.get('eve_lab_name', None)

    eve_ops = eve_lab(eve_lab_name=eve_lab_name, eve_ip=eve_ip, eve_user=eve_user, eve_password=eve_password)

    main_parser = argparse.ArgumentParser(prog='eve',
                                          description='EVE-NG tools, A Utility to make operations with EVE-NG more friendly.',
                                          epilog="mailto:basim.alyy@gmail, blog:http://basimaly.wordpress.com/",
                                          add_help=True)

    subprasers = main_parser.add_subparsers(dest='operation',
                                            # used only within the python code and as namespace key "args.operation"
                                            title="Available Commands",
                                            required=False)

    lab_ops = subprasers.add_parser(name='lab',
                                    help='Do Lab Operation')

    snapshot_ops = subprasers.add_parser(name='snapshot',
                                         help='Do Snapshot Operation')

    lab_g1 = lab_ops.add_mutually_exclusive_group(required=False)
    lab_g1.add_argument("--describe",
                         action="store_true",
                         required=False,
                         help="Describe the lab",
                         )

    lab_g2 = lab_ops.add_argument_group()
    lab_g2.add_argument("--action",
                        choices=["start", "stop","list"],
                        required=False,
                        help="Do operation over nodes",
                        )
    lab_g2.add_argument("--nodes",
                        default="all",
                        required=False,
                        help="list of nodes with comma separated",
                        )


    snap_g1 = snapshot_ops.add_argument_group()
    snap_g1.add_argument("--list", action="store_true", required=False, help="list a snapshot")

    snap_g2 = snapshot_ops.add_argument_group()
    snap_g2.add_argument("--ops", choices=["create",
                                           "revert",
                                           "delete"], required=False, help="Create a snapshot")
    snap_g2.add_argument("--snapshot", required=False, help="snapshot name")
    snap_g2.add_argument("--nodes", required=False, help="list of nodes with comma separated", default="all")

    args, extra = main_parser.parse_known_args()
    if args.operation == "lab":
        if args.describe:
            print(eve_ops.describe())
        elif args.action:
            if args.action == "list":
                print(eve_ops.describe())
            else:
                eve_ops.nodes_ops(ops=args.action, nodes=args.nodes)

    elif args.operation == "snapshot":
        if args.list:
            print(eve_ops.list_snapshots())
        elif args.ops:
            if args.snapshot:
                eve_ops.snapshot_ops(snapshotname=args.snapshot, ops=args.ops)
            else:
                print("Please provide snapshot name! (--snapshot)")
                exit(1)