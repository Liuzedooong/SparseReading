"""A repeated slot ID must not suppress a new question or source revision."""
import asyncio
import json

from sparseread.core.orchestrator import SparseReadingOrchestrator
from sparseread.core.tools import SroReadTool


def setup(tmp_path):
    path = tmp_path / 'registry.txt'
    path.write_text('The public registry had 5,705 community-built skills.\n\n'
                    'The registry was collected on 15 July 2026.\n')
    return path, SparseReadingOrchestrator(tmp_path)


def request(question='How many community-built skills were in the public registry?'):
    return {'goal': 'Answer the requested registry fact', 'type_hint': 'text',
            'slots': [{'id': 'q1', 'question': question, 'expected': 'fact'}]}


def read(sro, target, hint, mode='collect'):
    return json.loads(asyncio.run(SroReadTool(sro).execute(
        target=target, mode=mode, hint=hint)))['evidence_pack']


def test_same_slot_id_new_question_returns_new_evidence(tmp_path):
    path, sro = setup(tmp_path)
    first = read(sro, {'path': str(path)}, request())
    second = read(sro, {'artifact_id': first['artifact_id']},
                  request('What date was the registry collected?'))
    assert '15 July 2026' in json.dumps(second['slot_digest'])
    assert second['slot_digest']['slots'][0]['candidate'] != first['slot_digest']['slots'][0]['candidate']


def test_same_length_content_update_invalidates_old_evidence(tmp_path):
    path, sro = setup(tmp_path)
    first = read(sro, {'path': str(path)}, request())
    original = path.read_bytes()
    path.write_bytes(original.replace(b'5,705', b'6,806'))
    assert len(original) == path.stat().st_size
    second = read(sro, {'artifact_id': first['artifact_id']}, request())
    assert '6,806' in second['slot_digest']['slots'][0]['candidate']
    assert '5,705' not in second['slot_digest']['slots'][0]['candidate']


def test_updated_source_does_not_retain_native_search_guard(tmp_path):
    path, sro = setup(tmp_path)
    read(sro, {'path': str(path)}, request())
    assert sro.has_text_slot_digest(path)
    path.write_bytes(path.read_bytes().replace(b'5,705', b'6,806'))
    assert not sro.has_text_slot_digest(path)


def test_focus_new_need_is_not_replaced_by_old_collect(tmp_path):
    path, sro = setup(tmp_path)
    first = read(sro, {'path': str(path)}, request())
    second = read(sro, {'artifact_id': first['artifact_id']},
                  {'goal': 'Locate the registry collection date', 'needles': ['15 July 2026']}, 'focus')
    assert second['evidence'] and '15 July 2026' in json.dumps(second['evidence'])


def test_identical_request_still_reuses_existing_candidates(tmp_path):
    path, sro = setup(tmp_path)
    first = read(sro, {'path': str(path)}, request())
    second = read(sro, {'artifact_id': first['artifact_id']}, request())
    assert second['slot_digest']['slots'] == first['slot_digest']['slots']
    assert 'already' in second['summary']


def test_explicit_verification_remains_available(tmp_path):
    path, sro = setup(tmp_path)
    first = read(sro, {'path': str(path)}, request())
    verified = read(sro, {'artifact_id': first['artifact_id']},
                    {'goal': 'Verify the count in the source', 'needles': ['5,705']}, 'verify')
    assert verified['evidence'] and not verified.get('error')
