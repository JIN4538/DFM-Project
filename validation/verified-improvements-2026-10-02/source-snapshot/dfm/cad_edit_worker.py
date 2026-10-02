import hashlib
import json
from pathlib import Path
import sys
from .cad_edit_pairs import read_shape, round_corners, write_step


def main(folder):
    try:
        request = json.loads((folder/'request.json').read_text(encoding='utf8'))
        shape = read_shape(folder/'before.step')
        if 'pockets' in request:
            from .multi_cad_edit import round_multiple_corners
            after, result = round_multiple_corners(shape, request['pockets'])
        else:
            after, result = round_corners(shape, request['pocket'], request['radius'])
            result['direction'] = list(request['pocket']['direction'])
        from .cad_graph import extract_graph
        import math
        import numpy as np
        # Face IDs for preview must belong to the exported/re-imported STEP,
        # because export can reorder OCCT topology.
        result['after_sha256'] = write_step(after, folder/'after.step')
        exported = read_shape(folder/'after.step')
        from amdfm.cad_worker import integrated_properties
        if not math.isclose(integrated_properties(exported)['volume_mm3'], result['after_volume_mm3'], rel_tol=1e-7, abs_tol=1e-6):
            raise ValueError('Exported STEP volume differs from the checked edit')
        measurements = extract_graph(exported)['measurements']
        result['rounded_face_ids'] = []
        for edit in result.get('edits', [result]):
            low, high = np.asarray(edit['edit_bounds_mm'], dtype=float)
            ids = [m['face_id'] for m in measurements
                if m['surface_kind'] == 1 and math.isclose(m['radius_mm'], edit['after_corner_radius_mm'], rel_tol=1e-7, abs_tol=1e-7)
                and np.all(np.asarray(m['centroid_mm']) >= low-1e-6) and np.all(np.asarray(m['centroid_mm']) <= high+1e-6)]
            if len(ids) != edit['modified_corner_edges']:
                raise ValueError('Rounded CAD faces cannot be mapped for preview')
            edit['rounded_face_ids'] = ids
            if edit is not result:
                result['rounded_face_ids'].extend(ids)
        if not result.get('edits'):
            result['rounded_face_ids'] = ids
        if len(result['rounded_face_ids']) != result['modified_corner_edges']:
            raise ValueError('Rounded CAD faces cannot be mapped for preview')
        if len(set(result['rounded_face_ids'])) != len(result['rounded_face_ids']):
            raise ValueError('Rounded face mapping overlaps between pocket edits')
        from .edit_reinspection import inspect_export
        result['remeasurement'] = inspect_export(shape, exported, request.get('pockets', [request]), result)
        result['before_sha256'] = hashlib.sha256((folder/'before.step').read_bytes()).hexdigest()
        (folder/'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        return 0
    except Exception as error:
        (folder/'result.json').write_text(json.dumps(dict(error=str(error))), encoding='utf8')
        return 1


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1])))
