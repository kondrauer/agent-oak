"""Helper script to render the map graph as pdf."""

import matplotlib.pyplot as plt
import networkx as nx
from networkx.drawing.nx_agraph import graphviz_layout

from agent_oak.executor.navigation import build_game_map_graph
from agent_oak.parser.maps import parse_maps

if __name__ == "__main__":
    by_name, by_id = parse_maps()

    graph = build_game_map_graph(by_name)

    pos = graphviz_layout(graph, prog="sfdp")
    plt.figure(figsize=(24, 18))
    nx.draw(graph, pos, with_labels=True, node_size=300, font_size=5, width=0.5)

    plt.savefig("graph.pdf", bbox_inches="tight")  # good for printing
    plt.show()
