"""Matched real insert/delete traces; no timing extrapolation or replicated data."""
import argparse
import time
from pathlib import Path
import numpy as np
from verdi.common import SEED, read, save, signature
from verdi.owner import ConfiguredOwner, ConfiguredFlatOwner, binding
from verdi.retrieval import ExperimentClient, Transport, reachable, oracle
from verdi.cache import load_cache, paper_inputs


def run(features, output, sizes=(1000, 10000), operations=50):
    meta, x, training = load_cache(features); q = x
    folder = Path(output) / 'updates'
    folder.mkdir(parents=True, exist_ok=True)
    identity = {'features': meta['files_sha256'], 'operations': operations, 'sizes': list(sizes),
                'source_code': __import__('verdi.common',fromlist=['runtime']).runtime()['code_sha256']}
    config = folder / 'config.json'
    if config.exists() and read(config) != identity:
        raise RuntimeError('Update configuration changed; choose a new result directory')
    save(config, identity)
    summary = {'dataset': meta['dataset'], 'traces': [], 'skipped_sizes': [],
               'scope': 'Identical real insert/delete IDs per layout; shuffled layout order; '
                        'timers exclude post-update oracle, validation and transfer. Bytes are newly '
                        'materialized object payloads. Current tree publisher traverses the full tree; '
                        'publication latency does not establish an O(log N) implementation.'}
    for n in sizes:
        if n < 20 or len(x) < n + operations or operations >= n:
            summary['skipped_sizes'].append(n)
            continue
        for pattern in ('insert', 'delete', 'mixed'):
            result_path = folder / f'{n}_{pattern}.json'
            if result_path.exists():
                summary['traces'].append(read(result_path))
                continue
            rng = np.random.default_rng(SEED + n)
            deletes = rng.permutation(n)[:operations].tolist()
            inserts = rng.permutation(np.arange(n, len(x)))[:operations].tolist()
            trace = [(pattern, int(inserts[i] if pattern == 'insert' else deletes[i]))
                     for i in range(operations)] if pattern != 'mixed' else [
                         ('insert', int(inserts[i // 2])) if i % 2 == 0 else ('delete', int(deletes[i // 2]))
                         for i in range(operations * 2)]
            owners = {'tree': ConfiguredOwner(dict(enumerate(x[:n])), training, **binding(meta)),
                      'flat': ConfiguredFlatOwner(dict(enumerate(x[:n])), training, **binding(meta))}
            snapshots = {name: owner.publish() for name, owner in owners.items()}
            ids = paper_inputs()[meta['dataset']]['target_image_indices'][:10]
            rows = []
            for step, (kind, iid) in enumerate(trace):
                for name in np.random.default_rng(SEED + step).permutation(list(owners)):
                    owner = owners[str(name)]
                    previous = reachable(owner, snapshots[name])
                    previous_store = set(owner.store)
                    previous_records = dict(owner.records)
                    begin = time.perf_counter()
                    owner.insert(iid, x[iid]) if kind == 'insert' else owner.delete(iid)
                    maintenance_ms = (time.perf_counter() - begin) * 1000
                    begin = time.perf_counter()
                    snapshots[name] = owner.publish()
                    publication_ms = (time.perf_counter() - begin) * 1000
                    values = owner.tree.features if name == 'tree' else owner.features
                    if name == 'tree':
                        owner.tree.check()
                    current = reachable(owner, snapshots[name])
                    new = set(owner.store) - previous_store
                    assert new <= current
                    assert all(owner.records[i] == previous_records[i] for i in set(values) & set(previous_records))
                    eligible=[i for i in ids if i in values]; assert eligible; qi = eligible[step % len(eligible)]
                    top, _, _ = ExperimentClient(owner, Transport(owner.store), snapshots[name]).search(
                        q[qi], k=11, batch=16, mode='full' if name == 'tree' else 'flat_fine')
                    assert top == oracle(values, q[qi], 11)
                    rows.append({'step': step, 'operation': kind, 'record_id': iid, 'layout': str(name),
                                 'count_after': len(values), 'maintenance_ms': maintenance_ms,
                                 'publication_ms': publication_ms, 'total_ms': maintenance_ms + publication_ms,
                                 'new_payload_bytes': sum(len(owner.store[h]) for h in new),
                                 'new_objects': len(new), 'reuse_fraction': len(previous & current) / len(current),
                                 'surviving_records_unchanged': True, 'query_exact': True, 'query_image_id': qi, 'neighbor_ids': [i for _,i in top if i!=qi][:10]})
                if step % 10 == 0:
                    print(f'Updates N={n} {pattern}: {step+1}/{len(trace)}', flush=True)
            aggregates = []
            for layout in ('tree', 'flat'):
                for operation in sorted({r['operation'] for r in rows}):
                    rr = [r for r in rows if r['layout'] == layout and r['operation'] == operation]
                    aggregates.append({'layout': layout, 'operation': operation, 'operations': len(rr),
                                       'median_total_ms': float(np.median([r['total_ms'] for r in rr])),
                                       'p95_total_ms': float(np.quantile([r['total_ms'] for r in rr], .95)),
                                       'median_maintenance_ms': float(np.median([r['maintenance_ms'] for r in rr])),
                                       'median_publication_ms': float(np.median([r['publication_ms'] for r in rr])),
                                       'mean_new_payload_bytes': float(np.mean([r['new_payload_bytes'] for r in rr])),
                                       'all_exact': all(r['query_exact'] for r in rr)})
            result = {'initial_n': n, 'pattern': pattern, 'steps': len(trace), 'rows': rows, 'summary': aggregates}
            save(result_path, result)
            summary['traces'].append(result)
    save(folder / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--features', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--sizes', nargs='+', type=int, default=[1000, 10000])
    p.add_argument('--operations', type=int, default=50)
    a = p.parse_args()
    run(a.features, a.output, a.sizes, a.operations)
