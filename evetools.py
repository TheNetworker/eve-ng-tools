from pprint import pprint
import functools
from prettytable import PrettyTable
import requests
import json
import os
import urllib3
import subprocess
import time
import argparse
import yaml
import netaddr
import csv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
debug = 0
api_endpoints = {

    "login": "/api/auth/login",
    "auth": "/api/auth",
    "labs": "/api/labs/{0}",
    "nodes": "/api/labs/{0}/nodes",
    "node": "/api/labs/{0}/nodes/{1}",
    "node_interfaces": "/api/labs/{0}/nodes/{1}/interfaces",
    "networks": "/api/labs/{0}/networks",
    "network": "/api/labs/{0}/networks/{1}",
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
        self.eve_lab_name = eve_lab_name.strip() + ".unl" if eve_lab_name.split(".")[
                                                                 -1] != 'unl' else eve_lab_name.strip()
        self.headers = {'Accept': 'application/json', "Content-Type": "application/json", }
        self.qemu_bin = "qemu-img"
        self.lab_id = self._get(api_endpoints["labs"].format(self.eve_lab_name), ["id"], format="json")[0]['id']
        self.user_tenant = self._get(api_endpoints["auth"], format="json")['data']['tenant']

    def update_cookies(func):
        @functools.wraps(func)
        def wrapper_decorator(self, *args, **kwargs):

            self.eve_auth_data = {
                'username': self.eve_user,
                'password': self.eve_password,
                'html5': -1
            }

            auth = requests.post(url=self.eve_url + api_endpoints["login"],
                                 headers=self.headers,
                                 verify=False,
                                 data=json.dumps(self.eve_auth_data),
                                 )

            if auth.status_code == requests.codes.ok:
                # print("Authentication successful")
                self.eve_cookies = auth.cookies
            else:
                print("Authentication failed")
                print(auth.request.url)
                print(auth.status_code)
                exit(1)
            value = func(self, *args, **kwargs)
            return value

        return wrapper_decorator

    #   @property
    #   def lab_id(self):
    #       return self._get(api_endpoints["labs"].format(self.eve_lab_name),["id"], format="json")[0]['id']

    # @property
    # def user_tenant(self):
    #     return self._get(api_endpoints["auth"], format="json")['data']['tenant']

    @property
    def lab_home_directory(self):
        # print(self.user_tenant)
        lab_dir = os.path.join("/opt/unetlab/tmp/{0}".format(self.user_tenant), self.lab_id)
        # try:
        #     os.listdir(lab_dir)
        # except FileNotFoundError:
        #     print("Lab home directory is not found on the server: {}".format(lab_dir))
        #     exit(1)
        return lab_dir

    @update_cookies
    def _get(self, api_endpoint, fields=[], format="pretty"):

        if fields:  # initialize the table
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

    def _post(self, api_endpoint, body):
        _ = requests.post(url=self.eve_url + api_endpoint,
                          headers=self.headers,
                          verify=False,
                          cookies=self.eve_cookies,
                          data=json.dumps(body),
                          )
        if _.status_code == requests.codes.created:
            self.data = _.json().get('data', None)

        else:
            print("unable to post the data")
            print(_.request.url)
            print(_.status_code)
            pprint(body)

    def _put(self, api_endpoint, body):
        _ = requests.put(url=self.eve_url + api_endpoint,
                         headers=self.headers,
                         verify=False,
                         cookies=self.eve_cookies,
                         data=json.dumps(body),
                         )
        if _.status_code in (requests.codes.ok, requests.codes.created):
            self.data = _.json().get('data', None)

        else:
            print("unable to put the data")
            print(_.request.url)
            print(_.status_code)
            pprint(body)

    def _delete(self, api_endpoint, ):
        _ = requests.delete(url=self.eve_url + api_endpoint,
                            headers=self.headers,
                            verify=False,
                            cookies=self.eve_cookies,
                            )
        if _.status_code in (requests.codes.ok, requests.codes.accepted):

            self.data = _.json().get('data', None)

        elif _.status_code in (requests.codes.no_content, requests.codes.not_found):
            print("data is not found")
            self.data = None

        else:
            print("unable to delete the data")
            print(_.request.url)
            print(_.status_code)

    def get_nodes(self, include_qcow2=True):
        all_nodes_temp = self._get(api_endpoint=api_endpoints["nodes"].format(self.eve_lab_name),
                                   fields=["name", "id", "template", "status", "image", "url", "cpu", "ram",
                                           "ethernet", "firstmac"],
                                   format="json")
        self.nodes = []
        if include_qcow2:
            the_dir = os.listdir(self.lab_home_directory)
            for node_id in the_dir:
                # TODO a bit slow, need to optimize it, may by with glob?

                # print("op1")
                node_directory = f"{self.lab_home_directory}/{node_id}"
                # print(node_directory)
                # print("finish op1")
                # try:
                #    os.listdir(node_directory)
                # except FileNotFoundError:
                #    print("Node directory is not found on the server: {}".format(node_directory))
                #    exit(1)

                # print("Getting nodes")
                node_qcow2_files = [os.path.join(node_directory, f) for f in os.listdir(node_directory) if
                                    f.endswith('.qcow2')]

                # print("finish getting qcow2")
                # expensive operation and might overwhelm the eve server, so it's better to move processing to python instead (took 24s vs 12s)
                # node_dict = self._get(api_endpoint=api_endpoints["node"].format(self.eve_lab_name, node_id),
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

        # pprint(self.nodes)
        return self.nodes

    def interfaces_to_ids_in_node(self, node_name, include_qcow2=False):

        interface_to_id = {}
        node_id = self._get_node_id_by_name(node_name)
        all_node_intfs = self._get(
            api_endpoint=api_endpoints["node_interfaces"].format(self.eve_lab_name, node_id)).get("data").get(
            "ethernet")
        for idx, intf_record in enumerate(all_node_intfs):
            interface_to_id[intf_record['name']] = idx

        return interface_to_id

    def _filter_node(self, all_nodes, desired_nodes_name):
        tmp = desired_nodes_name.strip().split(",")
        final_list_of_nodes_obj = []
        for i in tmp:
            for node in all_nodes:
                if i == node["name"]:
                    final_list_of_nodes_obj.append(node)
                    break
        return final_list_of_nodes_obj

    def _get_node_id_by_name(self, node_name):
        lab_nodes = self.get_nodes(include_qcow2=False)
        try:
            return self._filter_node(lab_nodes, node_name)[0].get("id", None)
        except IndexError:
            print("Node name {} is not found in the lab".format(node_name))
            exit(1)

    def _get_intf_id_by_intf_name(self, node_name, node_interface_name):
        lab_node_interfaces = self.interfaces_to_ids_in_node(node_name)

        return lab_node_interfaces.get(node_interface_name, None)

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
        #
        # print(self._get(api_endpoints["networks"].format(self.eve_lab_name),["name","id","type","count","linkstyle"],format="pretty"))

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
        # print(node_qcow2)
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
            final_list_of_nodes = self._filter_node(all_nodes=lab_nodes, desired_nodes_name=nodes)

        for node in final_list_of_nodes:
            if node["status"] != 0:
                print("Please ensure the domain is down before working over the snapshots: '{}'".format(node["name"]))
                exit(1)

            for f in node["qcow2_files"]:
                command = [self.qemu_bin, "snapshot", flags[ops], "{}".format(snapshotname), "{}".format(f)]
                output_raw = subprocess.run(command, capture_output=True)
                if output_raw.returncode == 0:
                    print("successfully applied operation: '{}' over doamin: '{}' with snapshotname: '{}' ".format(ops,
                                                                                                                   node[
                                                                                                                       "name"],
                                                                                                                   snapshotname))
                    print(output_raw.stdout.decode("utf-8").strip())
                else:
                    print(
                        "Error on applying operation: '{}' over doamin: '{}' with snapshotname: '{}' ".format(ops, node[
                            "name"], snapshotname))
                    print(output_raw.stderr.decode("utf-8").strip())

    def _cmd_execute_local(self, cmd_string):
        cmd = cmd_string.strip().split()
        output_raw = subprocess.run(cmd, capture_output=True)

        if output_raw.returncode == 0:
            return True, output_raw.stdout.decode("utf-8").strip()
        else:
            return False, output_raw.stderr.decode("utf-8").strip()

    def nodes_ops(self, ops, nodes="all", includes_qcow2=False, delay=0):
        stop = 0
        lab_nodes = self.get_nodes(include_qcow2=includes_qcow2)
        # pprint(lab_nodes)
        if nodes == "all":
            final_list_of_nodes = lab_nodes

        else:
            final_list_of_nodes = self._filter_node(all_nodes=lab_nodes, desired_nodes_name=nodes)
            if not final_list_of_nodes:
                print("No nodes found with name: '{}'".format(nodes))
                exit(1)

        if ops == "init":
            temp_dict = final_list_of_nodes
            nodes_spec = os.environ.get('eve_nodes_spec', [])
            if not nodes_spec:
                print("Please specify the eve_nodes_spec in the environment variable: eve_nodes_spec")
                exit(1)
            _ = nodes_spec.split(",")
            _ = [x.strip() for x in _]
            nodes_spec_list = [{"name": x.split(":")[0], "desired_size": x.split(":")[1]} for x in _]
            # print("nodes_spec_list: {}".format(nodes_spec_list))
            # print("temp_dict_list: {}".format(temp_dict))
            for spec in nodes_spec_list:
                for index, node in enumerate(temp_dict):
                    # print(spec["name"])
                    # print(node["name"])
                    # print("------------")
                    if node["name"] == spec["name"]:
                        final_list_of_nodes[index]["desired_size"] = spec["desired_size"]
                        # pprint(node)
                        # print("---break")
                        break  # we found it, no need to continue

        # pprint(final_list_of_nodes)
        for node in final_list_of_nodes:
            print("->Applying operation: '{}' on node: '{}'".format(ops, node["name"]))
            if ops == "start" and node["status"] != stop:
                print(" Node already started!")

            elif ops == "stop" and node["status"] == stop:
                print(" Node already stopped!")

            elif ops == "init":
                for spec in nodes_spec_list:
                    # print("spec: {}".format(spec["name"]))
                    # print("node_name: {}".format(node["name"]))
                    # print("----------")
                    if spec["name"] == node["name"]:
                        print(" stopping the node: {}".format(node["name"]))
                        self.nodes_ops("stop", node["name"])  # recursive call

                        print(" initializing node: {}".format(node["name"]))

                        for f in node["qcow2_files"]:
                            rm_command = "rm -rf {}".format(f)
                            qcow2_create_cmd = "{} create -f qcow2 {} {}".format(self.qemu_bin, f, node["desired_size"])
                            # print(qcow2_create_cmd)
                            ret_code_is_true, output = self._cmd_execute_local(cmd_string=rm_command)
                            if not ret_code_is_true:
                                print("  Error on removing file: {}".format(f))
                                print(output)
                                exit(1)

                        print(" creating new disk on node: {} with size: {} GB".format(node["name"],
                                                                                       node["desired_size"]))
                        ret_code_is_true, output = self._cmd_execute_local(cmd_string=qcow2_create_cmd)
                        if not ret_code_is_true:
                            print("  Error on creating the file: {} on node: {}".format(f, node["name"]))
                            print(output)
                            exit(1)
                        break
            elif ops == "get_console_port":
                print("{}".format(node["url"].split(":")[-1]))
                break
            else:
                url = api_endpoints["node"].format(self.eve_lab_name, node["id"]) + "/{}".format(ops)
                if delay:
                    time.sleep(delay)
                if ops == "stop":
                    url = url + "/stopmode=3"  # required for eve-ng pro only
                self._get(api_endpoint=url)
                time.sleep(0.1)

    def get_bridge_id_by_name(self, bridge_name):
        all_bridges = self._get(api_endpoint=api_endpoints["networks"].format(self.eve_lab_name)).get("data")
        # pprint(all_bridges)
        for k, v in all_bridges.items():
            if v["name"] == bridge_name:
                return v["id"]

    def add_new_bridge(self, bridge_name, ):
        request_payload = {
            "type": "bridge",
            "name": bridge_name,
            "left": "35",
            "top": "25",
            "visibility": "1",
            "count": "1"
        }
        self._post(api_endpoint=api_endpoints["networks"].format(self.eve_lab_name), body=request_payload)
        return (self.get_bridge_id_by_name(bridge_name))

    def p2p_intfs_ops(self, src_node, dst_node, src_intf, dst_intf, ops='add'):
        src_node_id = self._get_node_id_by_name(node_name=src_node)
        dst_node_id = self._get_node_id_by_name(node_name=dst_node)
        src_intf_id = self._get_intf_id_by_intf_name(node_name=src_node, node_interface_name=src_intf)
        dst_intf_id = self._get_intf_id_by_intf_name(node_name=dst_node, node_interface_name=dst_intf)
        p2p_bridge_name = "p2p_br_{}_{}_{}_{}".format(src_node_id, dst_node_id, src_intf_id, dst_intf_id)

        if ops == 'add':
            p2p_bridge_id = self.add_new_bridge(bridge_name=p2p_bridge_name, )

            src_request_payload = {
                src_intf_id: p2p_bridge_id  # interface_id:bridge_id
            }

            dst_request_payload = {
                dst_intf_id: p2p_bridge_id  # interface_id:bridge_id
            }

            bridge_visibility_payload = {"visibility": "0"}

            self._put(api_endpoint=api_endpoints["node_interfaces"].format(self.eve_lab_name, src_node_id),
                      body=src_request_payload)

            self._put(api_endpoint=api_endpoints["node_interfaces"].format(self.eve_lab_name, dst_node_id),
                      body=dst_request_payload)

            # print("  setting visibility to 0 for bridge: {}".format(p2p_bridge_name))
            self._put(api_endpoint=api_endpoints["network"].format(self.eve_lab_name, p2p_bridge_id),
                      body=bridge_visibility_payload)


        elif ops == 'remove':
            print("  removing bridge: {}".format(p2p_bridge_name))
            p2p_bridge_id = self.get_bridge_id_by_name(bridge_name=p2p_bridge_name)
            self._delete(api_endpoint=api_endpoints["network"].format(self.eve_lab_name, p2p_bridge_id))

        time.sleep(0.1)

    def get_ansible_data(self, file_path):  # Day1 and Day2
        print("working on file path: {}".format(file_path))

        if not os.path.isfile(file_path):
            print("  Error: file path: {} does not exist".format(file_path))
            exit(1)

        with open(file_path, "r", encoding='utf8') as stream:
            topology = yaml.safe_load(stream)
            mgmt_subnet = topology["mgmt_subnet"]  # better to fail if mgmt_subnet is not defined
            igp_protocol = topology.get("igp", "")
            network_nodes = topology.get("networks_nodes", [])
            vm_nodes = topology.get("vms", [])
            connections = topology.get("connections", [])
            ip_mgmt_subnet = netaddr.IPNetwork(mgmt_subnet)

        # Generate the output for the vars_all_pxe_ztp_hosts in the ansible directory (Day0)
        print(
            '\n\n->Day0: Please add the following output to "vars_all_pxe_ztp_hosts.yaml" inside your ansible directory')
        print("lab_" + self.eve_lab_name.split(".unl")[0] + ":")
        print("  network_nodes:")

        lab_nodes = self.get_nodes(include_qcow2=False)
        lo_ip = {}
        isis = {}
        for node in network_nodes if network_nodes else []:
            loopback_last_octet = int(node["loopback"].split(".")[-1])
            mgmt_ip = str(ip_mgmt_subnet[loopback_last_octet])

            mac = self._filter_node(lab_nodes, node["node_that_will_do_pxe"])[0]["firstmac"]
            template = self._filter_node(lab_nodes, node["node_that_will_do_pxe"])[0]["template"]

            if "vqfxre" in template:
                os_release = "junos-vqfx"
            elif "vmx" in template:
                os_release = "junos-vmx"
            else:
                os_release = "unknown"

            print('   - {{ name: {}, mac: "{}", ip: {}, netmask: {}, role: {}, os_release: {} }}'.format(
                node["name"],
                mac,
                mgmt_ip,
                mgmt_subnet.split("/")[-1],
                node["role"],
                os_release,
            ))

            lo_ip[node["name"]] = node["loopback"]
            tmp = "{:0>3}{:0>3}{:0>3}{:0>3}".format(*node["loopback"].split("."))

            if igp_protocol == "isis":
                isis_area = "49.0000"
                if node["role"] == "peagg" or node["role"] == "preagg":
                    isis_area = "49.0001"  # instruct the L1L2 router to advertise the attached-bit (i.e. advertise the default-route) for seamless MPLS architecture
                lo_iso_id = "{}.{}.{}.{}.00".format(isis_area, tmp[0:4], tmp[4:8], tmp[8:12])
                isis[node["name"]] = {"lo_iso_id": lo_iso_id}

        # Generate the output for the lab_vars in the lab directory (Day1)
        p2p_ip = {}

        for connection in connections if connections else []:
            ip_network = netaddr.IPNetwork(connection["p2p_subnet"])

            src_record = {"port": connection["src_intf"], "ip": str(ip_network[0]),
                          "peer_node": connection["dst_node"], "pport": connection["dst_intf"],
                          "peer_ip": str(ip_network[1])}

            dst_record = {"port": connection["dst_intf"], "ip": str(ip_network[1]),
                          "peer_node": connection["src_node"], "pport": connection["src_intf"],
                          "peer_ip": str(ip_network[0])}

            p2p_ip.setdefault(connection["src_node"], []).append(src_record)
            p2p_ip.setdefault(connection["dst_node"], []).append(dst_record)

        print("\n\n->Day1: Please add the following output to lab_vars.yaml inside your lab directory")
        print("p2p_ip:")
        for k in p2p_ip:
            print(" {}:".format(k))
            for v in p2p_ip[k]:
                print("  - {{ port: {}, ip: {}, peer_node: {}, pport: {}, peer_ip: {} }}".format(v["port"],
                                                                                                 v["ip"],
                                                                                                 v["peer_node"],
                                                                                                 v["pport"],
                                                                                                 v["peer_ip"],

                                                                                                 ))

            print("\n")

        print("lo_ip:")
        for k in lo_ip:
            print(" {}: {}".format(k, lo_ip[k]))
        print("\n")

        if igp_protocol == "isis":
            print("isis:")
            for k in isis:
                print(" {}:".format(k))
                print("  lo_iso_id: {}".format(isis[k]["lo_iso_id"]))

                # if node["role"] == "preagg" or node["role"] == "peagg":
                #     print(node)
                #     print("  level: 1")
                # else:
                #     print("  level: 2")

        # print(yaml.dump(p2p_ip,  default_flow_style=False, allow_unicode=True, sort_keys=True, indent=2,explicit_start=False,default_style='',width=1000))

    def rack_and_stack_nodes_in_topology(self, file_path, ops="add", cnx_body="", flavor="", transform=""):  # Day0
        print("->working on file path: {}".format(file_path))
        print(
            "->Important [1]: Please don't login to EVE-NG GUI until this operation is finished to avoid interrupting the API")

        print(
            "->Important [2]: This method is not intended to be used for connecting nodes with bridges. Only between VM nodes")
        if cnx_body:
            # '{ "src_node": "IGW2_R21" , "dst_node": "IGWRR1_R34" , "src_intf": "ge-0/0/2" ,"dst_intf": "ge-0/0/2"}'
            cnx_body = json.loads(cnx_body)
            self.p2p_intfs_ops(src_node=cnx_body["src_node"],
                               src_intf=cnx_body["src_intf"],
                               dst_node=cnx_body["dst_node"],
                               dst_intf=cnx_body["dst_intf"], ops=ops)
        else:
            if not os.path.isfile(file_path):
                print("  Error: file path: {} does not exist".format(file_path))
                exit(1)

            if flavor == "apstra":
                with open(file_path, "r", encoding='utf8') as csv_file:
                    csv_reader = csv.reader(csv_file, delimiter=',')
                    line_count = 0
                    connections = []
                    if transform:
                        original_intf_prefix = transform.split("_to_")[0]
                        new_intf_prefix = transform.split("_to_")[1]
                    for row in csv_reader:
                        connection = {}
                        if line_count == 0:
                            # print(f'Column names are {", ".join(row)}')
                            line_count += 1
                        else:
                            src_node = row[2].strip()
                            src_intf = row[5].strip().replace(original_intf_prefix, new_intf_prefix)
                            dst_node = row[7].strip()
                            dst_intf = row[10].strip().replace(original_intf_prefix, new_intf_prefix)
                            connection["src_node"] = src_node
                            connection["src_intf"] = src_intf
                            connection["dst_node"] = dst_node
                            connection["dst_intf"] = dst_intf
                            if src_node and src_intf and dst_node and dst_intf:
                                connections.append(connection)
                            line_count += 1
                    #         print('->operating over nodes: "{}" and "{}" over port:"{}" and port:"{}"'.format(src_node, dst_node, src_intf, dst_intf))
                    # print(f'Processed {line_count} lines.')

                # print(connections)
                # exit(0)

            else:
                with open(file_path, "r", encoding='utf8') as stream:
                    topology = yaml.safe_load(stream)
                    connections = topology.get("connections", [])

            for num, connection in enumerate(connections):
                print('->[{}/{}]operating over nodes: "{}" and "{}" over port:"{}" and port:"{}"'.format(
                    num + 1,
                    len(connections),
                    connection["src_node"],
                    connection["dst_node"],
                    connection["src_intf"],
                    connection["dst_intf"],
                ))

                self.p2p_intfs_ops(src_node=connection["src_node"],
                                   src_intf=connection["src_intf"],
                                   dst_node=connection["dst_node"],
                                   dst_intf=connection["dst_intf"], ops=ops)

            # time.sleep(32)


if __name__ == '__main__':

    eve_ip = os.environ.get('eve_ip', None)
    eve_user = os.environ.get('eve_user', 'admin')
    eve_password = os.environ.get('eve_password', 'eve')
    eve_pod = str(os.environ.get('eve_pod', 0))
    eve_lab_name = os.environ.get('eve_lab_name', None)
    eve_lab_cnx_file = os.environ.get('eve_lab_cnx_file', None)

    eve_ops = eve_lab(eve_lab_name=eve_lab_name, eve_ip=eve_ip, eve_user=eve_user, eve_password=eve_password)

    # for testing only
    # pprint(eve_ops.interfaces_to_ids_in_node(node_name="C2_R3"))
    # pprint(eve_ops.add_new_bridge(bridge_name="bassem"))

    # eve_ops.connect_p2p_intfs(src_node="C2_R3", dst_node="C2_R4", src_intf="ge-0/0/0", dst_intf="ge-0/0/0")

    # exit(1)
    # end the testing
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

    lab_g1.add_argument("--rack_and_stack",
                        action="store_true",
                        required=False,
                        help="Connect the nodes with each other according to the topology file stored in env variable eve_lab_cnx_file",
                        )

    lab_g1.add_argument("--cnx_body",
                        required=False,
                        help="provide the body of the connection request",
                        )

    lab_g1.add_argument("--de_rack_and_stack",
                        action="store_true",
                        required=False,
                        help="disconnect the nodes from each other according to the topology file stored in env variable eve_lab_cnx_file",
                        )

    lab_g1.add_argument("--get_ansible_data",
                        action="store_true",
                        required=False,
                        help="Get the data required by ansible playbooks to configure Day1 according to the topology file stored in env variable eve_lab_cnx_file",
                        )

    lab_g2 = lab_ops.add_argument_group()
    lab_g2.add_argument("--action",
                        choices=["start", "stop", "list", "init", "get_console_port"],
                        required=False,
                        help="Do operation over nodes",
                        )
    lab_g2.add_argument("--nodes",
                        default="all",
                        required=False,
                        help="list of nodes with comma separated",
                        )

    lab_g2.add_argument("--flavor",
                        required=False,
                        help="provide the flavor of the lab mgmt solution",
                        choices=['apstra']
                        )

    lab_g2.add_argument("--delay",
                        required=False,
                        help="provide the delay in seconds between each node operation",
                        default=0
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
        elif args.rack_and_stack:
            if args.flavor == 'apstra':
                eve_ops.rack_and_stack_nodes_in_topology(ops="add", file_path=eve_lab_cnx_file, flavor='apstra',
                                                         transform='eth_to_ge-0/0/')
            else:
                eve_ops.rack_and_stack_nodes_in_topology(ops="add", file_path=eve_lab_cnx_file)


        elif args.cnx_body:
            eve_ops.rack_and_stack_nodes_in_topology(ops="add", file_path=eve_lab_cnx_file, cnx_body=args.cnx_body)

        elif args.de_rack_and_stack:
            eve_ops.rack_and_stack_nodes_in_topology(ops="remove", file_path=eve_lab_cnx_file)

        elif args.get_ansible_data:
            eve_ops.get_ansible_data(file_path=eve_lab_cnx_file)

        elif args.action:
            if args.action == "list":
                print(eve_ops.describe())
            elif args.action == "init":
                eve_ops.nodes_ops(ops=args.action, nodes=args.nodes, includes_qcow2=True)
            else:
                eve_ops.nodes_ops(ops=args.action, nodes=args.nodes, includes_qcow2=False, delay=int(args.delay))

    elif args.operation == "snapshot":
        if args.list:
            print(eve_ops.list_snapshots())
        elif args.ops:
            if args.snapshot:
                eve_ops.snapshot_ops(snapshotname=args.snapshot, ops=args.ops, nodes=args.nodes)
            else:
                print("Please provide snapshot name! (--snapshot)")
                exit(1)

'''
*Lab operation*
eve-tools lab --describe
eve-tools lab --action start 
eve-tools lab --action stop --nodes issu-0,issu-1

eve-tools lab --action init

eve-tools lab --get_ansible_data
eve-tools lab --rack_and_stack
eve-tools lab --rack_and_stack --flavor apstra
eve-tools lab --cnx_body '{json_payload}'
eve-tools lab --de_rack_and_stack


*Snapshots operation*
eve-tools snapshot --list

eve-tools snapshot --ops create --snapshot test_after_migration
eve-tools snapshot --ops revert --snapshot test_after_migration
eve-tools snapshot --ops delete --snapshot test_after_migration


*curl*

curl -iv --insecure -b /tmp/cookie -c /tmp/cookie -X POST  -H 'Content-type: application/json' -d '{"username":"admin","password":"eve", "html5": "-1"}' https://10.99.100.252/api/auth/login

curl  --silent --insecure -c  /tmp/cookie -b /tmp/cookie -X GET -H 'Content-type: application/json' https://10.99.100.252/api/labs/5G_Core_in_CSP.unl/nodes | python -mjson.tool


'''