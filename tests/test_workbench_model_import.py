"""Native design import roundtrips geometry without importing trusted state."""
import json

import pytest

from app.workbench.demo import cafe_candidate
from app.workbench.model_import import import_native_model
from app.workbench.models import Project
from app.workbench.store import WorkbenchStore


def exported_model():
    source = Project(references=[{'id': 'reference-image', 'kind': 'image', 'name': 'original.jpg',
                                  'url': '/api/workbench/projects/old/references/reference-image'},
                                 {'id': 'product-link', 'kind': 'link', 'name': 'Product page',
                                  'url': 'https://example.com/chair', 'text': 'Remote source text'}])
    source = Project.model_validate({**source.model_dump(mode='json'), **cafe_candidate(source)['patch']})
    source.baseline_revision = 1
    source.confirmed_revision = source.revision
    source.acknowledged_limits = True
    source.preservation.status = 'verified'
    source.evidence = []
    from app.workbench.models import Evidence
    source.evidence.append(Evidence(statement='Historical image observation', source_ids=['reference-image'], status='observed'))
    return source


def test_import_creates_new_identity_and_preserves_geometry(tmp_path):
    store = WorkbenchStore(tmp_path)
    original = store.save(exported_model())
    restored = import_native_model(store, original.model_dump_json().encode())
    assert restored.id != original.id
    assert restored.revision == 1
    assert restored.parts == original.parts
    assert restored.materials == original.materials
    assert restored.baseline_revision is None
    assert restored.confirmed_revision is None
    assert not restored.acknowledged_limits
    assert not restored.scale.confirmed
    assert restored.preservation.status == 'inferred'
    assert all(not joint.confirmed for joint in restored.joints)
    assert store.load(original.id) == original


def test_missing_attachments_remain_explicit_provenance_not_live_files(tmp_path):
    restored = import_native_model(WorkbenchStore(tmp_path), exported_model().model_dump_json().encode())
    image = next(reference for reference in restored.references if reference.id == 'reference-image')
    link = next(reference for reference in restored.references if reference.id == 'product-link')
    assert image.kind == 'note' and image.url == ''
    assert '尚未读取' in image.text
    assert link.kind == 'link' and link.url == 'https://example.com/chair'
    assert restored.evidence[0].status == 'unknown'
    assert restored.evidence[0].source_ids == ['reference-image']


def test_proposal_json_is_not_misread_as_full_native_model(tmp_path):
    with pytest.raises(ValueError):
        import_native_model(WorkbenchStore(tmp_path), json.dumps({'summary': 'patch', 'patch': {}}).encode())


def test_import_cannot_carry_review_consent_into_new_project(tmp_path):
    from app.workbench.models import ReviewState, ReviewConfirmation
    from app.workbench.review import review_projection
    source = exported_model()
    item = review_projection(source)['dimensions'][0]
    source.review_state = ReviewState(confirmations={
        'dimension:'+item['id']: ReviewConfirmation(fingerprint=item['fingerprint'], revision=1, decision='keep')})
    imported = import_native_model(WorkbenchStore(tmp_path), source.model_dump_json().encode())
    assert imported.review_state is None
    assert review_projection(imported)['enabled'] is False
    assert all(not item['confirmed'] for item in review_projection(imported)['dimensions'])
