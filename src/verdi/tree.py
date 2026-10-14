"""Owner-side balanced tree maintenance for image vectors."""
from dataclasses import dataclass, field
import numpy as np

def normalise(x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ValueError('Expected a finite feature matrix')
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError('Zero feature vector')
    return x / norms


@dataclass(eq=False)
class Node:
    nid: int
    ids: list = field(default_factory=list)
    left: object = None
    right: object = None
    parent: object = None
    height: int = 0
    count: int = 0
    minid: int = 0
    counts: object = None
    mask: object = None
    caps: object = None
    totalcap: int = 0

    @property
    def leaf(self):
        return self.left is None


class Tree:
    """Owner-side mutable AVL state; immutable snapshot publication is separate."""
    def __init__(self, features, groups, capacity=16):
        self.features = {int(i): np.asarray(b, dtype=np.int64).copy() for i, b in features.items()}
        self.groups, self.capacity, self.nextid, self.rotations = groups, capacity, 0, 0
        self.locations = {}
        self.root = self.build(sorted(self.features)) if self.features else None

    def node(self, **kwargs):
        self.nextid += 1
        return Node(self.nextid, **kwargs)



    def build(self, ids):
        if len(ids) <= self.capacity:
            return self.refresh(self.node(ids=list(ids)))
        a, b = self.split(ids)
        return self.refresh(self.node(left=self.build(a), right=self.build(b)))

    def rotate_left(self, n):
        p, right = n.parent, n.right
        n.right = right.left
        right.left, right.parent = n, p
        self.refresh(n)
        self.refresh(right)
        self.rotations += 1
        return right

    def rotate_right(self, n):
        p, left = n.parent, n.left
        n.left = left.right
        left.right, left.parent = n, p
        self.refresh(n)
        self.refresh(left)
        self.rotations += 1
        return left

    def balance(self, n):
        self.refresh(n)
        if n.leaf:
            return n
        difference = n.left.height - n.right.height
        if difference > 1:
            if n.left.left.height < n.left.right.height:
                n.left = self.rotate_left(n.left)
            return self.rotate_right(n)
        if difference < -1:
            if n.right.right.height < n.right.left.height:
                n.right = self.rotate_right(n.right)
            return self.rotate_left(n)
        return n


    def insert(self, i, b):
        if i in self.features:
            raise ValueError('Duplicate ID')
        self.features[i] = np.asarray(b, dtype=np.int64).copy()
        def visit(n):
            if n.leaf:
                n.ids.append(i)
                if len(n.ids) > self.capacity:
                    a, c = self.split(n.ids)
                    n.ids, n.left, n.right = [], self.build(a), self.build(c)
                return self.balance(n)
            child = min([n.left, n.right], key=lambda c: (self.route(b, c), c.count, c.nid))
            if child is n.left:
                n.left = visit(n.left)
            else:
                n.right = visit(n.right)
            return self.balance(n)
        self.root = visit(self.root) if self.root else self.build([i])
        self.root.parent = None

    def delete(self, i):
        n = self.locations.pop(i)
        n.ids.remove(i)
        del self.features[i]
        if n.ids:
            self.refresh(n)
        else:
            parent = n.parent
            if parent is None:
                self.root = None
                return
            sibling = parent.right if parent.left is n else parent.left
            grand = parent.parent
            sibling.parent = grand
            if grand is None:
                self.root = sibling
            elif grand.left is parent:
                grand.left = sibling
            else:
                grand.right = sibling
            n = grand
        while n is not None:
            parent, was_left = n.parent, n.parent is not None and n.parent.left is n
            if not n.leaf and n.left.leaf and n.right.leaf and n.left.count + n.right.count <= self.capacity:
                n.ids = n.left.ids + n.right.ids
                n.left = n.right = None
            updated = self.balance(n)
            if parent is None:
                self.root = updated
                updated.parent = None
            elif was_left:
                parent.left = updated
            else:
                parent.right = updated
            n = parent

    def nodes(self):
        if self.root is None:
            return []
        result, stack = [], [self.root]
        while stack:
            n = stack.pop()
            result.append(n)
            if not n.leaf:
                stack.extend([n.left, n.right])
        return result
