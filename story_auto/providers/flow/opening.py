"""Cookie-owned reference video at the canonical Hybrid Opening boundary."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from uuid import UUID, uuid4

from story_auto.core.artifacts import atomic_write_bytes, sha256_file, read_json
from story_auto.core.project.lock import ProjectLock
from story_auto.core.visual.opening_builder import import_opening_clip
from story_auto.providers.byteplus_seedance.opening import _project, _load_slot, _persist, _safe_view, _now
from .cookie_accounts import FlowCookieAccountStore
from .cookie_session import NamedCookieSessionFactory
from .rpc_transport import FlowRpcGenerator, RpcError, enabled, validate_intent, verify_attribution, verify, identity, JOURNAL_NAME
from .session import FlowRuntime

PROVIDER_ID = 'flow_cookie'


def reset_unused_flow_cookie_opening(runtime_root, project_id, slot_id):
    """Explicitly release a sealed pre-effect intent; preserve all audit evidence."""
    runtime, paths, _ = _project(runtime_root, project_id)
    with ProjectLock(runtime, project_id):
        _, slot = _load_slot(paths, project_id, slot_id)
        observed = slot.get('api_generation') or {}
        if observed.get('provider') != PROVIDER_ID:
            raise RpcError('FLOW_COOKIE_RESET_NOT_AVAILABLE')
        account_id, attempt_id = observed['account_id'], observed['attempt_id']
    lock_name = 'flow_cookie_' + hashlib.sha256(account_id.encode()).hexdigest()[:24]
    with ProjectLock(runtime, lock_name), ProjectLock(runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id)
        generation = slot.get('api_generation') or {}
        if generation.get('attempt_id') != attempt_id or generation.get('provider') != PROVIDER_ID:
            raise RpcError('FLOW_COOKIE_ATTEMPT_IDENTITY_MISMATCH')
        try:
            directory = paths.artifact_path(f'assets/opening/flow/{attempt_id}')
            journal = verify(read_json(directory / JOURNAL_NAME))
            flow = _runtime(runtime, generation['project_url'])
            bound = identity(flow, generation['request'], [paths.artifact_path(generation['reference_path'])])
            bound.update(attempt_directory=str(directory.resolve()), session_binding={
                'mode':'cookie_owned', 'account_id':account_id, 'revision':generation['revision']})
            no_effect = (journal.get('identity') == bound and journal.get('state') == 'PREPARING'
                         and journal.get('upload_attempts') == 0 and journal.get('submit_attempts') == 0
                         and journal.get('reference_id') is None and journal.get('output_id') is None)
        except Exception:
            no_effect = False
        if not no_effect:
            raise RpcError('FLOW_COOKIE_NO_EFFECT_PROOF_REQUIRED')
        slot.setdefault('provider_attempt_history', []).append({**generation, 'reset_at':_now(),
                                                               'reset_reason':'SEALED_ZERO_EFFECT_INTENT'})
        del slot['api_generation']
        _persist(paths, manifest)
    return _safe_view(runtime.root, project_id)


def _runtime(runtime, project_url):
    from urllib.parse import urlsplit
    if not isinstance(project_url, str):
        raise RpcError('FLOW_COOKIE_PROJECT_INVALID')
    parsed = urlsplit(project_url)
    identity = parsed.path.removeprefix('/project/')
    try:
        valid_id = str(UUID(identity)) == identity
    except ValueError:
        valid_id = False
    if (parsed.scheme != 'https' or parsed.netloc != 'flow.google.com'
            or parsed.path != '/project/' + identity or not valid_id
            or parsed.query or parsed.fragment):
        raise RpcError('FLOW_COOKIE_PROJECT_INVALID')
    return FlowRuntime(runtime.flow_profile, 'cookie-owned://named', project_url, identity)


def generate_flow_cookie_opening(runtime_root, project_id, slot_id, *, account_id='',
                                 project_url='', reference_path=None, store=None,
                                 session_factory=None, timeout_seconds=60):
    """One explicit request; any persisted attempt is recovery-only on re-entry."""
    runtime, paths, config = _project(runtime_root, project_id)
    with ProjectLock(runtime, project_id):
        _, slot = _load_slot(paths, project_id, slot_id)
        existing = slot.get('api_generation') or {}
        if existing and existing.get('provider') != PROVIDER_ID:
            raise RpcError('OPENING_PROVIDER_MISMATCH')
        if existing.get('status') == 'SUCCEEDED':
            return _safe_view(runtime.root, project_id)
        if existing:
            if (account_id and account_id != existing.get('account_id')
                    or project_url and project_url != existing.get('project_url')
                    or reference_path is not None):
                raise RpcError('FLOW_COOKIE_ATTEMPT_IDENTITY_MISMATCH')
            account_id = existing['account_id']
            project_url = existing['project_url']
        elif str(config.settings.get('hybrid_visual', {}).get('opening_provider_policy', 'AUTO')).upper() != 'AUTO':
            raise RpcError('OPENING_PROVIDER_POLICY_MISMATCH')
    active_store = store if store is not None else FlowCookieAccountStore()
    account = active_store.get_account(account_id)
    flow = _runtime(runtime, project_url)
    lock_name = 'flow_cookie_' + hashlib.sha256(account_id.encode()).hexdigest()[:24]
    with ProjectLock(runtime, lock_name):
        with ProjectLock(runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id)
            generation = slot.get('api_generation')
            recovery_only = generation is not None
            if generation:
                if (generation.get('provider') != PROVIDER_ID
                        or generation.get('account_id') != account_id
                        or generation.get('revision') != account['revision']
                        or generation.get('project_url') != project_url
                        or generation.get('prompt_sha256') != slot.get('prompt_sha256')
                        or generation.get('slot_duration') != slot.get('duration_seconds')):
                    raise RpcError('FLOW_COOKIE_ATTEMPT_IDENTITY_MISMATCH')
                if generation.get('status') == 'SUCCEEDED':
                    return _safe_view(runtime.root, project_id)
            else:
                if not enabled(flow):
                    raise RpcError('FLOW_RPC_DISABLED')
                duration = float(slot.get('duration_seconds') or 0)
                if not math.isfinite(duration) or not 4 <= duration <= 8:
                    raise RpcError('FLOW_COOKIE_SLOT_DURATION_UNSUPPORTED')
                request = {'request_id': slot_id, 'media_type': 'VIDEO', 'prompt': slot['prompt'],
                           'target_duration': 8, 'aspect_ratio': '16:9', 'output_count': 1,
                           'model_override': 'abra_r2v_8s'}
                if reference_path is None:
                    raise RpcError('FLOW_COOKIE_REFERENCE_REQUIRED')
                reference = Path(reference_path)
                validate_intent(request, [reference])
                attempt_id = uuid4().hex
                reference_rel = f'assets/opening/flow/{attempt_id}/reference.png'
                durable_reference = paths.artifact_path(reference_rel)
                atomic_write_bytes(durable_reference, reference.read_bytes())
                validate_intent(request, [durable_reference])
                generation = {'provider': PROVIDER_ID, 'provider_model': 'abra_r2v_8s',
                              'attempt_id': attempt_id, 'account_id': account_id,
                              'revision': account['revision'], 'project_url': project_url,
                              'project_identity': flow.project_identity,
                              'prompt_sha256': slot['prompt_sha256'], 'slot_duration': duration,
                              'request': request, 'reference_path': reference_rel,
                              'reference_sha256': sha256_file(durable_reference),
                              'status': 'PREPARING', 'created_at': _now(), 'updated_at': _now()}
                slot['api_generation'] = generation
                _persist(paths, manifest)
            # Never reconstruct an existing provider request from mutable UI inputs.
            request = dict(generation['request'])
            reference = paths.artifact_path(generation['reference_path'])
            if sha256_file(reference) != generation['reference_sha256']:
                raise RpcError('FLOW_COOKIE_REFERENCE_CHANGED')
            attempt_id = generation['attempt_id']
            destination = paths.artifact_path(f'assets/opening/flow/{attempt_id}/output.mp4')
            factory = session_factory or NamedCookieSessionFactory(account_id, generation['revision'], store=active_store)
            if getattr(factory, 'binding', None) != {'mode':'cookie_owned','account_id':account_id,'revision':generation['revision']}:
                raise RpcError('FLOW_COOKIE_ACCOUNT_BINDING_INVALID')

        def update(**values):
            with ProjectLock(runtime, project_id):
                current, current_slot = _load_slot(paths, project_id, slot_id)
                record = current_slot.get('api_generation') or {}
                if (record.get('attempt_id') != attempt_id
                        or current_slot.get('prompt_sha256') != generation['prompt_sha256']):
                    raise RpcError('FLOW_COOKIE_ATTEMPT_IDENTITY_MISMATCH')
                record.update(values, updated_at=_now())
                _persist(paths, current)

        rpc = FlowRpcGenerator(flow, session_factory=factory, timeout_seconds=timeout_seconds)
        try:
            output = rpc.run(request, [reference], destination, recovery_only=recovery_only,
                             before_boundary=lambda: update(status='SUBMITTING'))
            receipt = verify_attribution(rpc.last_settings)
            if receipt['output_sha256'] != sha256_file(output):
                raise RpcError('FLOW_RPC_OUTPUT_HASH_MISMATCH')
            update(status='ACQUIRING', provider_task_id=receipt['output_id'],
                   provider_task_status='succeeded', rpc_settings=rpc.last_settings)
            return import_opening_clip(runtime.root, project_id, slot_id, output,
                                       original_filename=f'flow_{slot_id}.mp4',
                                       _provider_identity={'provider':PROVIDER_ID,
                                                           'provider_task_id':receipt['output_id'],
                                                           'account_id':account_id,
                                                           'revision':generation['revision'],
                                                           'project_identity':flow.project_identity})
        except Exception:
            # Preserve the attempt even for unknown errors. Re-entry is read-only;
            # no raw browser/provider exception or cookie reaches the UI.
            update(status='RECOVERY_REQUIRED', failure_class='FLOW_COOKIE_RECOVERY_REQUIRED')
            return _safe_view(runtime.root, project_id)
