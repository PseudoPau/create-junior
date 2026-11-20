"""Revision-checked review endpoints; navigation never implies user consent."""
from __future__ import annotations

from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException
from pydantic import Field
from app.workbench.models import Record
from app.workbench.store import RevisionConflict
from app.workbench.review import indexed_items, review_projection


class ReviewRevision(Record):
    expected_revision: int = Field(ge=1)


class ReviewDecision(ReviewRevision):
    category: Literal['dimension', 'board', 'node']
    id: str = Field(min_length=1, max_length=250)
    fingerprint: str = Field(min_length=1, max_length=128)
    decision: Literal['keep', 'adopt', 'custom'] = 'keep'


class BoardEdit(ReviewRevision):
    fingerprint: str = Field(min_length=1, max_length=128)
    length_mm: float = Field(gt=0, le=10000)
    width_mm: float = Field(gt=0, le=10000)
    thickness_mm: float = Field(gt=0, le=1000)
    material_id: str | None = Field(default=None, max_length=120)
    allow_redesign: bool = False


def create_review_router(store_source):
    router = APIRouter(prefix='/api/workbench')

    def store():
        return store_source() if callable(store_source) else store_source

    def load(project_id):
        try:
            return store().load(str(project_id))
        except FileNotFoundError:
            raise HTTPException(404, '找不到项目') from None

    @router.get('/projects/{project_id}/review')
    def review(project_id: UUID):
        return review_projection(load(project_id))

    @router.post('/projects/{project_id}/review/start')
    def start(project_id: UUID, body: ReviewRevision):
        with store().lock:
            project = load(project_id)
            if project.revision != body.expected_revision:
                raise HTTPException(409, '设计已更新，请重新读取核对内容。')
            if project.review_state is None:
                project = store().change(project.id, project.revision, {}, enable_review=True)
            return review_projection(project)

    @router.post('/projects/{project_id}/review/confirm')
    def confirm(project_id: UUID, body: ReviewDecision):
        with store().lock:
            project = load(project_id)
            if project.revision != body.expected_revision:
                raise HTTPException(409, '设计已更新，请重新读取核对内容。')
            item = indexed_items(project).get(f'{body.category}:{body.id}')
            if item is None:
                raise HTTPException(404, '找不到当前核对项')
            if not item.get('fingerprint'):
                raise HTTPException(422, '缺少可核对的几何定义，请先补充模型。')
            if item['fingerprint'] != body.fingerprint:
                raise HTTPException(409, '核对项内容已改变，请重新查看。')
            joint_ids = set()
            if body.category == 'node':
                from app.workbench.engine import build_checks
                part_ids = set(item['part_ids'])
                failures = [issue for issue in build_checks(project.model_dump(mode='json'))
                            if issue['severity'] == 'blocker' and issue['code'] != 'joint_unconfirmed'
                            and (not issue.get('part_ids') or part_ids.intersection(issue['part_ids']))]
                if failures:
                    raise HTTPException(422, {'message': '先处理这组节点的问题。', 'checks': failures})
                joint_ids = set(item['joint_ids'])
            try:
                updated = store().change(project.id, project.revision, {},
                    accepted_joint_ids=joint_ids, review_actions=[body.model_dump(exclude={'expected_revision'})])
            except RevisionConflict as error:
                raise HTTPException(409, str(error)) from None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            return review_projection(updated)

    @router.post('/projects/{project_id}/review/boards/{group_id}/edit-preview')
    def edit_board(project_id: UUID, group_id: str, body: BoardEdit):
        from app.workbench.board_edit import board_edit_preview
        with store().lock:
            project = load(project_id)
            if project.revision != body.expected_revision:
                raise HTTPException(409, '设计已更新，请重新读取板件。')
            group = next((item for item in review_projection(project)['board_groups'] if item['id'] == group_id), None)
            if group is None:
                raise HTTPException(404, '找不到当前板件组')
            if body.fingerprint != group['fingerprint']:
                raise HTTPException(409, '板件内容已改变，请重新查看。')
            try:
                proposal = board_edit_preview(project, group, body.model_dump())
            except ValueError as error:
                raise HTTPException(422, {'code': 'agent_required', 'message': str(error),
                    'group_id': group_id, 'part_ids': group['part_ids'],
                    'requested': body.model_dump(exclude={'expected_revision', 'fingerprint'})}) from None
            if proposal.get('preservation_conflict') and not body.allow_redesign:
                raise HTTPException(409, {'code': 'preservation_decision',
                    'message': '这项板件修改会改变原椅特征。可保持原样，或明确作为改款预览。',
                    'can_redesign': True})
            store().save_proposal(project.id, proposal)
            return proposal

    return router
