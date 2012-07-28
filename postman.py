#!/usr/bin/env python2.7
from __future__ import print_function

__author__ = 'Ralf Kistner'


import sys
import csv
import networkx as nx
import xml.dom.minidom as minidom

def pairs(lst, circular=False):
    """
    Loop through all pairs of successive items in a list.

    >>> list(pairs([1, 2, 3, 4]))
    [(1, 2), (2, 3), (3, 4)]
    >>> list(pairs([1, 2, 3, 4], circular=True))
    [(1, 2), (2, 3), (3, 4), (4, 1)]
    """
    i = iter(lst)
    first = prev = item = i.next()
    for item in i:
        yield prev, item
        prev = item
    if circular:
        yield item, first

def import_csv_graph(file):
    """
    Example:

    import_csv_graph(open("test.csv", "rb"))

    Does not handle multigraphs yet (more than 1 edge between the same 2 nodes).

    Each row must have the following (in this order):

    * Start node ID
    * End node ID
    * Length in meters
    * Edge name or ID
    * Start longitude, for example 18.4167
    * Start latitude, for example -33.9167
    * End longitude
    * End latitude
    """
    reader = csv.reader(file)
    graph = nx.Graph()
    for row in reader:
        if not row[0].isdigit():
            # Skip any non-integer rows (header rows)
            continue

        start_node, end_node, length = map(int, row[:3])
        id, start_lon, start_lat, end_lon, end_lat = row[3:8]
        graph.add_edge(start_node, end_node, weight=length, id=id)

        # We keep the GPS coordinates as strings
        graph.node[start_node]['longitude'] = start_lon
        graph.node[start_node]['latitude'] = start_lat
        graph.node[end_node]['longitude'] = end_lon
        graph.node[end_node]['latitude'] = end_lat

    return graph


def validate_graph(graph):
    # The graph may contain multiple components, but we can only handle one connected component. If the graph contains
    # more than one connected component, we only use the largest one.
    components = nx.connected_component_subgraphs(graph)
    components.sort(key=lambda c: c.size(), reverse=True)

    if len(components) > 1:
        print("Warning: input graph contains multiple components, only using the first one", file=sys.stderr)

    main_component = components[0]
    return main_component



def odd_graph(graph):
    """
    Given a graph G, construct a graph containing only the vertices with odd degree from G. The resulting graph is
    fully connected, with each weight being the shortest path between the nodes in G.
    """
    result = nx.Graph()
    odd_nodes = [n for n in graph.nodes() if graph.degree(n) % 2 == 1]
    for u in odd_nodes:
        # We calculate the shortest paths twice here, but the overall performance hit is low
        paths = nx.shortest_path(graph, source=u)
        lengths = nx.shortest_path_length(graph, source=u)
        for v in odd_nodes:
            if u <= v:
                # We only add each edge once
                continue
            # The edge weights are negative for the purpose of max_weight_matching (we want the minimum weight)
            result.add_edge(u, v, weight=-lengths[v], path=paths[v])

    return result


def as_gpx(graph, track_list, name=None):
    """
    Convert a list of tracks to GPX format
    Example:

    >>> g = nx.Graph()
    >>> g.add_node(1, latitude="31.1", longitude="-18.1")
    >>> g.add_node(2, latitude="31.2", longitude="-18.2")
    >>> g.add_node(3, latitude="31.3", longitude="-18.3")
    >>> print(as_gpx(g, [{'points': [1,2,3]}]))
    <?xml version="1.0" ?><gpx version="1.0"><trk><name>Track 1</name><number>1</number><trkseg><trkpt lat="31.1" lon="-18.1"><ele>1</ele></trkpt><trkpt lat="31.2" lon="-18.2"><ele>2</ele></trkpt><trkpt lat="31.3" lon="-18.3"><ele>3</ele></trkpt></trkseg></trk></gpx>
    """
    doc = minidom.Document()

    root = doc.createElement("gpx")
    root.setAttribute("version", "1.0")
    doc.appendChild(root)

    if name:
        gpx_name = doc.createElement("name")
        gpx_name.appendChild(doc.createTextNode(name))
        root.appendChild(gpx_name)

    for i, track in enumerate(track_list):
        nr = i+1
        track_name = track.get('name') or ("Track %d" % nr)
        trk = doc.createElement("trk")
        trk_name = doc.createElement("name")
        trk_name.appendChild(doc.createTextNode(track_name))
        trk.appendChild(trk_name)
        trk_number = doc.createElement("number")
        trk_number.appendChild(doc.createTextNode(str(nr)))
        trk.appendChild(trk_number)
        trkseg = doc.createElement("trkseg")

        for u in track['points']:
            longitude = graph.node[u].get('longitude')
            latitude = graph.node[u].get('latitude')
            trkpt = doc.createElement("trkpt")
            trkpt.setAttribute("lat", latitude)
            trkpt.setAttribute("lon", longitude)
            ele = doc.createElement("ele")
            ele.appendChild(doc.createTextNode(str(u)))
            trkpt.appendChild(ele)
            trkseg.appendChild(trkpt)

        trk.appendChild(trkseg)
        root.appendChild(trk)

    return doc.toxml()

def write_csv(graph, nodes, out):
    writer = csv.writer(out)
    writer.writerow(["Start Node", "End Node", "Segment Length", "Segment ID", "Start Longitude", "Start Latitude", "End Longitude", "End Latitude"])
    for u, v in pairs(nodes, False):
        length = graph[u][v]['weight']
        id = graph[u][v]['id']
        start_latitude = graph.node[u].get('latitude')
        start_longitude = graph.node[u].get('longitude')
        end_latitude = graph.node[v].get('latitude')
        end_longitude = graph.node[v].get('longitude')
        writer.writerow([u, v, length, id, start_longitude, start_latitude, end_longitude, end_latitude])

def edge_sum(graph):
    total = 0
    for u, v, data in graph.edges(data=True):
        total += data['weight']
    return total

def chinese_postman_path(graph):
    """
    Given a graph, return a list of node id's forming the shortest chinese postman path.
    """

    # Find all the nodes with an odd degree, and create a graph containing only them
    odd = odd_graph(graph)

    # Find the best matching of pairs of odd nodes
    matching = nx.max_weight_matching(odd, True)

    # Copy the original graph to a multigraph (so we can add more edges between the same nodes)
    eulerian_graph = nx.MultiGraph(graph)

    # For each matched pair of odd vertices, connect them with the shortest path between them
    for u, v in matching.items():
        if v <= u:
            # Each matching occurs twice in the matchings: (u => v) and (v => u). We only count those where v > u
            continue
        edge = odd[u][v]
        path = edge['path'] # The shortest path between the two nodes, calculated in odd_graph()

        # Add each segment in this path to the graph again
        for p, q in pairs(path):
            eulerian_graph.add_edge(p, q, weight=graph[p][q]['weight'])

    # Now that we have an eulerian graph, we can calculate the eulerian circuit
    circuit = list(nx.eulerian_circuit(eulerian_graph))
    nodes = []
    for u, v in circuit:
        nodes.append(u)
    # Close the loop
    nodes.append(circuit[0][0])

    return eulerian_graph, nodes

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="input CSV file", type=argparse.FileType('rb'))
    parser.add_argument("--gpx", help="GPX output file", type=argparse.FileType('wb'))
    parser.add_argument("--csv", help="CSV output file", type=argparse.FileType('wb'))
    args = parser.parse_args()

    graph = import_csv_graph(args.input)
    graph = validate_graph(graph)


    eulerian_graph, nodes = chinese_postman_path(graph)

    in_length = edge_sum(graph)/1000.0
    path_length = edge_sum(eulerian_graph)/1000.0
    duplicate_length = path_length - in_length

    print("Total length of roads: %.3f km" % in_length)
    print("Total length of path: %.3f km" % path_length)
    print("Section visited twice: %.3f km" % duplicate_length)
    print("Node sequence:", nodes)

    if args.gpx:
        args.gpx.write(as_gpx(graph, [{'points': nodes}]))

    if args.csv:
        write_csv(graph, nodes, args.csv)
