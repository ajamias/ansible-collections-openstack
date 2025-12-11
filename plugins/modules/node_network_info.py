#!/usr/bin/python

# Copyright: (c) 2018, Terry Jones <terry.jones@example.org>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: node_network_info
short_description: Get information about networks attached to a baremetal node
author: Innabox
description:
  - Gather information about Neutron networks attached to an Ironic node
  - Returns details about network attachments and baremetal ports
options:
  nodes:
    description:
      - A list of node names or IDs
    type: list
    element: str
  network:
    description:
      - Filter by specific network name or ID
    type: str
extends_documentation_fragment:
  - openstack.cloud.openstack
'''

EXAMPLES = r'''
'''

RETURN = r'''
node_networks:
  description:
    - List of information about network attachments on the nodes
  returned: success
  type: list
  elements: dict
  contains:
    Node:
      description:
        - The name of the node
      returned: success
      type: str
    Node UUID:
      description:
        - The ID of the node
      returned: success
      type: str
    Node Ports:
      description:
        - A list of the node's port information
      returned: success
      type: list
      elements: dict
      contains:
        baremetal_port_uuid:
          description:
            - The ID of the baremetal port
          returned: success
          type: str
        mac_address:
          description:
            - The baremetal port's MAC address
          returned: success
          type: str
        network_port:
          description
            - A dict of info for the attached port
          returned: When baremetal port is attached
          type: dict
          contains:
            name:
              description:
                - The network port's name
              returned: When baremetal port is attached
              type: str
            uuid:
              description:
                - The network port's ID
              returned: When baremetal port is attached
              type: str
            fixed_ips:
              description:
                - A list of the network port's IPs
              returned: When baremetal port is attached
              type: list
              elements: str
        network:
          description:
            - A dict of info for the attached network
          returned: When a network is attached
          type: dict
          contains:
            name:
              description:
                - The network's name
              returned: When a network is attached
              type: str
            uuid:
              description:
                - The network's ID
              returned: When a network is attached
              type: str
            vlan_id:
              description:
                - The network's vlan ID
              returned: When a network is attached
              type: int
        floating_network:
          description:
            - A dict of info for the external network
          returned: When a floating IP is attached
          type: dict
          contains:
            name:
              description:
                - The external network's name
              returned: When an external network is attached
              type: str
            uuid:
              description:
                - The external network's ID
              returned: When an external network is attached
              type: str
            vlan_id:
              description:
                - The external network's vlan ID
              returned: When an external network is attached
              type: int
        trunk_uuid:
          description:
            - The parent network trunk's ID
          returned: When a parent network trunk is attached
          type: str
        trunk_networks:
          description:
            - A list of children trunk networks
          returned: When a parent network trunk is attached
          type: list
          elements: dict
          contains:
            name:
              description:
                - The child trunk's name
              returned: When a parent network trunk is attached
              type: str
            uuid:
              description:
                - The network's ID
              returned: When a parent network trunk is attached
              type: str
            vlan_id:
              description:
                - The network's vlan ID
              returned: When a parent network trunk is attached
              type: int
'''

from ansible_collections.openstack.cloud.plugins.module_utils.openstack import (
        OpenStackModule
)


class NodeNetworkInfoModule(OpenStackModule):
    argument_spec = dict(
        node=dict(),
        mac_address=dict(),
        network=dict(),
    )

    def run(self):
        filter_nodes = set(self.params['nodes'])
        baremetal_nodes = self.conn.baremetal.nodes(details=True)

        self._prefetch_resources()

        nodes = []
        for baremetal_node in baremetal_nodes:
            if (filter_nodes and
                    baremetal_node.id not in filter_nodes and
                    baremetal_node.name not in filter_nodes):
                continue

            baremetal_ports = self.conn.baremetal.ports(
                details=True, node_id=baremetal_node.id)

            network_infos = []
            for baremetal_port in baremetal_ports:
                network_info = {
                    'baremetal_port': baremetal_port,
                    'network_ports': [],
                    'networks': {
                        'parent': None,
                        'trunk': [],
                        'floating': None,
                    },
                    'floating_ip': None,
                    'port_forwardings': [],
                }

                network_port = None
                network_port_id = baremetal_port.internal_info.get(
                    "tenant_vif_port_id", None)

                if network_port_id:
                    network_port = self._network_ports_by_id.get(
                        network_port_id, None)

                if network_port:
                    parent, trunks, trunk_ports, floating = \
                        self._get_networks_from_port(network_port)

                    if not parent:
                        continue

                    floating_ip = self._floating_ips_by_port_id.get(
                        network_port.id, None)
                    network_info['network_ports'].append(network_port)
                    network_info['network_ports'].extend(trunk_ports)
                    network_info['networks']['parent'] = parent
                    network_info['networks']['trunk'] = trunks
                    network_info['networks']['floating'] = floating
                    network_info['floating_ip'] = floating_ip
                    network_info['port_forwardings'] = list(
                        self.conn.network.port_forwardings(floating_ip))

                elif self.params['network']:
                    continue

                network_infos.append(network_info)

            if network_infos:
                nodes.append({
                    'node': baremetal_node,
                    'network_info': network_infos
                })

    def _prefetch_resources(self):
        self._networks_by_id = {
            network.id: network for network in self.conn.network.networks()
        }
        self._network_ports_by_id = {
            port.id: port for port in self.conn.network.ports()
        }
        self._floating_ips_by_port_id = {
            fip.port_id: fip for fip in self.conn.network.ips()
        }

    def _get_networks_from_port(self, network_port):
        parent_network = self._networks_by_id[network_port.network_id]

        if (parent_network.name != self.params['network'] or
                parent_network.id != self.params['network']):
            return None, [], [], None

        trunk_networks = []
        trunk_ports = []
        if network_port.trunk_details:
            subport_infos = network_port.trunk_details["sub_ports"]
            for subport_info in subport_infos:
                subport = self._network_ports_by_id[subport_info["port_id"]]
                trunk_network = self._networks_by_id[subport.network_id]

                trunk_ports.append(subport)
                trunk_networks.append(trunk_network)

        floating_network_id = getattr(
            self._floating_ips_by_port_id.get(network_port.id),
            'floating_network_id',
            None
        )
        floating_network = self._networks_by_id.get(floating_network_id, None)

        return parent_network, trunk_networks, trunk_ports, floating_network


def main():
    module = NodeNetworkInfoModule()
    module()


if __name__ == "__main__":
    main()
