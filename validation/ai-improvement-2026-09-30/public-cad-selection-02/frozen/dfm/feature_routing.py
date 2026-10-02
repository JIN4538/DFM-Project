"""Validated CAD routing for frozen semantic and instance models.

The joint model chooses the class. On planar CAD, agreement from the planar
specialist can recover a low-confidence joint detection, but disagreement
cannot replace the joint class. All reported face IDs and dimensions remain
the original CAD measurements. No model weights or feature contracts change.
"""
from __future__ import annotations
import numpy as np
from .feature_learning import (CLASS_NAMES, CURVED_CLASS_NAMES, CURVED_CLASS_LABELS,
    CURVED_MODEL_PATH, load_model as load_semantic, predict_graph, recognize_graph)
from .feature_localization import load_model, predict_localization, components

POLICY_ID = 'cad-feature-agreement-v1'
MAX_CAD_FACES = 200


def _vote(probabilities, group):
    scores=np.log(np.maximum(probabilities[group],1e-12)).mean(0)
    result=np.exp(scores-scores.max())
    return result/result.sum()


def recognize_cad_features(graph):
    """Use the calibrated joint-class path, with existing unavailable fallback."""
    x=np.asarray(graph['x'])
    if x.ndim!=2 or len(x)<1:
        raise ValueError('Invalid CAD graph nodes')
    if len(x)>MAX_CAD_FACES or np.any(x[:,5]>.5):
        return dict(status='outside_training_domain',candidates=[],routing_policy=POLICY_ID)
    planar=bool(np.all(x[:,0]>.5))
    try:
        heads,backbone=load_model()
    except (ValueError,OSError,KeyError) as error:
        result=recognize_graph(graph,None if planar else load_semantic(CURVED_MODEL_PATH))
        result.update(routing_policy='legacy-feature-fallback',routing_fallback_reason=str(error))
        return result
    prediction=predict_localization(graph,heads,backbone)
    specialist=None
    if planar:
        try:
            specialist_model=load_semantic()
            raw=predict_graph(graph,specialist_model)
            specialist=np.zeros((len(x),len(CURVED_CLASS_NAMES)))
            specialist[:,[CURVED_CLASS_NAMES.index(n) for n in CLASS_NAMES]]=raw
        except (ValueError,OSError,KeyError):
            # A valid joint detection does not depend on the auxiliary model.
            specialist=None
    candidates=[]
    for group in components(np.asarray(graph['edges'],dtype=int).reshape(-1,2),
                            prediction['edge']>=heads['edge_threshold'],len(x)):
        q=_vote(prediction['semantic'],group); label=int(q.argmax())
        if label==24:continue
        confidence=float(q[label]); confidence_source='joint'
        if specialist is not None:
            other=_vote(specialist,group)
            if int(other.argmax())==label and float(other[label])>confidence:
                confidence=float(other[label]); confidence_source='planar_agreement'
        threshold=heads.get('class_thresholds',[heads.get('instance_threshold',.9)]*24)[label]
        if threshold is None or confidence<float(threshold):continue
        measured=[graph['measurements'][i] for i in group]
        candidates.append(dict(feature=CURVED_CLASS_NAMES[label],label=CURVED_CLASS_LABELS[label],
            face_ids=[int(m['face_id']) for m in measured],confidence=confidence,
            confidence_source=confidence_source,area_mm2=sum(m['area_mm2'] for m in measured),measured_faces=measured,
            bottom_face_ids=[int(graph['measurements'][i]['face_id']) for i in group if prediction['bottom'][i]>=heads['bottom_threshold']],
            localization_model_id=heads['model_id'],measurement_method='Learned instance boundary/bottom proposals; OCCT B-rep integration'))
    return dict(status='measured',model_id=backbone['model_id'],localization_model_id=heads['model_id'],
        routing_policy=POLICY_ID,candidates=candidates,evaluated_faces=len(x),threshold=heads.get('instance_threshold',.9),
        unconfirmed_classes=[CURVED_CLASS_NAMES[i] for i,t in enumerate(heads.get('class_thresholds',[])) if t is None])
