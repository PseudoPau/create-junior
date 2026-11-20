"""User review facts, derived from the same adopted model as the viewport.

Review is opt-in for the new workflow. Legacy projects remain readable and do
not acquire consent merely because they contain older boolean confirmations.
"""
from __future__ import annotations

from app.workbench.models import Project
from app.workbench.measurements import dimension_items
from app.workbench.review_groups import review_groups


def review_items(project: Project) -> dict:
    grouped = review_groups(project)
    dimensions = []
    for module in project.modules:
        if module.kind != 'support':
            continue
        for item in dimension_items(project, module.id):
            item = dict(item)
            item['id'] = f'{module.id}:{item["key"]}'
            item['category'] = 'dimension'
            dimensions.append(item)
    for category, name in [('board', 'board_groups'), ('node', 'node_groups')]:
        for item in grouped[name]:
            item['category'] = category
    return {'dimensions': dimensions, **grouped}


def indexed_items(project: Project) -> dict:
    groups = review_items(project)
    return {f'{item["category"]}:{item["id"]}': item
            for name in ('dimensions', 'board_groups', 'node_groups') for item in groups[name]}


def invalidate_review(previous: Project, data: dict) -> None:
    """Never trust confirmations supplied in an editable patch or AI candidate."""
    ledger = previous.review_state
    if ledger is None:
        data['review_state'] = None
        return
    candidate = Project.model_validate(data)
    items = indexed_items(candidate)
    retained = {}
    for key, record in ledger.confirmations.items():
        item = items.get(key)
        if item and item.get('fingerprint') and item['fingerprint'] == record.fingerprint:
            retained[key] = record.model_dump(mode='json')
    data['review_state'] = {'version': 1, 'confirmations': retained}


def apply_review_actions(data: dict, actions: list[dict] | None, enable: bool = False) -> None:
    if not actions and not enable:
        return
    project = Project.model_validate(data)
    items = indexed_items(project)
    ledger = data.get('review_state') or {'version': 1, 'confirmations': {}}
    for action in actions or []:
        key = f'{action["category"]}:{action["id"]}'
        item = items.get(key)
        if item is None or not item.get('fingerprint'):
            raise ValueError('当前对象无法确认，请先补齐模型定义。')
        if action['fingerprint'] != item['fingerprint']:
            raise ValueError('确认内容已改变，请重新查看当前对象。')
        ledger['confirmations'][key] = {
            'fingerprint': item['fingerprint'], 'revision': project.revision + 1,
            'decision': action.get('decision', 'keep'),
        }
    data['review_state'] = ledger


def review_projection(project: Project) -> dict:
    groups = review_items(project)
    records = project.review_state.confirmations if project.review_state else {}
    for name in ('dimensions', 'board_groups', 'node_groups'):
        for item in groups[name]:
            record = records.get(f'{item["category"]}:{item["id"]}')
            confirmed = bool(record and item.get('fingerprint') == record.fingerprint)
            item['confirmed'] = confirmed
            item['review_status'] = 'confirmed' if confirmed else 'needs_review'
            item['decision'] = record.decision if confirmed else None
    required = [item for name in ('dimensions', 'board_groups', 'node_groups') for item in groups[name]]
    complete = bool(groups['dimensions'] and groups['board_groups'] and groups['node_groups']) and all(
        item['confirmed'] for item in required)
    return {'revision': project.revision, 'enabled': project.review_state is not None,
            'complete': complete, 'remaining': sum(not item['confirmed'] for item in required), **groups}


def review_blockers(project: Project) -> list[dict]:
    if project.review_state is None:
        return []
    review = review_projection(project)
    if review['complete']:
        return []
    return [{'code': 'workflow_review_pending', 'severity': 'blocker', 'part_ids': [],
             'message': '先完成适己尺寸、板件组与节点组的核对，再生成当前版本加工包。'}]
