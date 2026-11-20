"""Revision artifacts remain immutable after subsequent design changes."""
import io
import base64
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workbench import api, exports
from app.workbench.store import WorkbenchStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'workbench_store', WorkbenchStore(tmp_path))
    return TestClient(app)


def test_export_refuses_missing_geometry_and_never_changes_design(client):
    project = client.post('/api/workbench/projects', json={'name':'Missing geometry'}).json()
    url = '/api/workbench/projects/' + project['id']
    response = client.post(url + '/exports', json={'expected_revision':project['revision']})
    assert response.status_code == 409
    assert client.get(url).json() == project
    assert client.get(url + '/exports').json() == {'exports':[]}


def test_export_binds_snapshot_and_retains_old_download(client, monkeypatch):
    project = client.post('/api/workbench/projects', json={'name':'Snapshot artifact'}).json()
    url = '/api/workbench/projects/' + project['id']
    # This test targets artifact lifecycle; geometry validation is tested separately.
    monkeypatch.setattr(exports, 'build_checks', lambda p: [])
    monkeypatch.setattr(exports, 'build_package', lambda p: {'revision':p['revision'],'drawings':[], 'cut_list':[], 'hardware':[], 'assembly_steps':[], 'coverage':{}})
    async def pdf(document):
        return b'%PDF-1.4\nartifact-fixture'
    monkeypatch.setattr(exports, 'render_pdf', pdf)
    first = client.post(url + '/exports', json={'expected_revision':1})
    assert first.status_code == 200
    result = first.json()
    assert client.get(url).json()['revision'] == 1
    saved = client.get(result['download_url']).content
    with zipfile.ZipFile(io.BytesIO(saved)) as archive:
        assert {'drawings.pdf','model/design.json','cut-list.csv','purchase.csv','hardware.csv'} <= set(archive.namelist())
    client.put(url, json={'expected_revision':1,'patch':{'name':'Changed'}})
    assert client.get(result['download_url']).content == saved
    assert client.get(url + '/exports').json()['exports'][0]['current'] is False
    assert client.post(url + '/exports', json={'expected_revision':1}).status_code == 409


def test_pdf_failure_preserves_design_and_allows_retry(client, monkeypatch):
    project = client.post('/api/workbench/projects', json={'name':'PDF retry'}).json()
    url = '/api/workbench/projects/' + project['id']
    monkeypatch.setattr(exports, 'build_checks', lambda p: [])
    monkeypatch.setattr(exports, 'build_package', lambda p: {'drawings':[], 'cut_list':[], 'hardware':[], 'assembly_steps':[], 'coverage':{}})
    async def unavailable(document):
        raise RuntimeError('printer unavailable')
    monkeypatch.setattr(exports, 'render_pdf', unavailable)
    assert client.post(url + '/exports', json={'expected_revision':1}).status_code == 503
    assert client.get(url).json() == project
    assert client.get(url + '/exports').json()['exports'] == []


def test_csv_names_cannot_inject_spreadsheet_formulas():
    content = exports.csv_bytes(['name'], [['=1+1']]).decode('utf-8-sig')
    assert "'=1+1" in content


@pytest.mark.parametrize('prefix', ['\t', '\r', '\n'])
def test_csv_control_prefixes_are_neutralized(prefix):
    content = exports.csv_bytes(['name'], [[prefix+'=1+1']]).decode('utf-8-sig')
    assert "'"+prefix+'=1+1' in content


def test_viewport_images_are_validated_and_embedded_with_snapshot():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), 'white').save(buffer, format='PNG')
    data = 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')
    images = exports.visual_images({'assembled':data, 'exploded':data})
    project = {'id':'project', 'name':'Chair', 'revision':7}
    package = {'drawings':[], 'cut_list':[], 'hardware':[], 'assembly_steps':[]}
    document = exports.package_html(project, package, images)
    assert document.count('data:image/png;base64,') == 2
    archive = exports.archive_bytes(project, package, b'%PDF', document, images)
    with zipfile.ZipFile(io.BytesIO(archive)) as result:
        assert result.read('views/assembled.png').startswith(b'\x89PNG')
        assert result.read('views/exploded.png').startswith(b'\x89PNG')
    with pytest.raises(Exception) as error:
        exports.visual_images({'assembled':'https://example.com/image.png'})
    assert error.value.status_code == 422


def test_cut_list_uses_normalized_thickness_axis():
    cut = {'stock_size_mm':[24,170,426], 'stock_dimensions_mm': {
        'width_mm':170, 'thickness_mm':24, 'length_mm':426}}
    assert exports.stock_dimensions(cut) == [170,24,426]
