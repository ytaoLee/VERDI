"""Image-to-image query and authenticated result-descriptor helpers."""
from .retrieval import ExperimentClient, flat_parse
from .protocol import node_parse


def image_search(owner, transport, snapshot, query, query_id=None, k=10, mode='full', batch=16):
    client = ExperimentClient(owner, transport, snapshot)
    protocol_k = k + (query_id is not None)
    top, stats, certificate = client.search(query, k=protocol_k, mode=mode, batch=batch)
    neighbors = [(score,i) for score,i in top if i != query_id][:k]
    assert len(neighbors) == k
    return neighbors, stats, certificate


def authenticated_slots(client, certificate):
    """Extract descriptors from an already verified search certificate."""
    objects = certificate['objects']
    root = bytes.fromhex(client.state['root'])
    if client.state.get('layout') == 'flat-list-v1':
        return {s[0]:s for s in flat_parse(objects[root])}
    slots = {}
    def visit(h):
        n = node_parse(objects[h])
        slots.update({s[0]:s for s in n['slots']})
        for child in n['children']:
            if child in objects:
                visit(child)
    visit(root)
    return slots
