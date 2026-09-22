"""Seed an isolated, provider-free Opening UI fixture. Never dispatches media."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_auto.core.project import RuntimeLayout, ProjectConfig, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder


def main():
    runtime = RuntimeLayout.from_root(Path(sys.argv[1])).ensure()
    project_id = 'prj_cookie_opening_preview'
    project_file = runtime.projects / project_id / 'project.json'
    if project_file.exists():
        print('Existing fixture preserved:', project_id)
    else:
        create_project(runtime, ProjectConfig(project_id, render_mode='hybrid_hook', settings={
            'hybrid_visual': {'cuj_enabled':True,'opening_provider_policy':'AUTO'},
            'render': {'width':320,'height':180,'fps':24,'pixel_format':'yuv420p'}}),
            '# Cookie Opening UI fixture\n\n## Narration\n\nA traveller watches the dawn. This is a provider-free interface fixture.\n')
        configure_opening_builder(runtime.root, project_id, shared_context='Engineering UI fixture, not quality acceptance.',
                                  slot_specs=[{'duration_seconds':6,'purpose':purpose,'prompt':prompt}
                                              for purpose,prompt in [('Hook','Sunrise over mountains'),('Develop','A traveller walks'),('End','The open valley')]])
        print('Created provider-free fixture:', project_id)
    if '--serve-fixture' in sys.argv:
        from story_auto.ui import create_server
        from story_auto.application.operator import OperatorServiceError
        server = create_server(runtime.root,port=0)
        service = server.RequestHandlerClass.service
        service.flow_cookie_connection_status = lambda: {
            'status':'CONFIGURED','configured':True,'live_verified':False,
            'accounts':[{'account_id':'ui-fixture-not-a-real-account','revision':1}],
            'generation_enabled':True,
            'generation_project_url':'https://flow.google.com/project/11111111-2222-3333-4444-555555555555'}
        def no_effect(*args, **kwargs):
            raise OperatorServiceError('UI_FIXTURE_PROVIDER_ACTION_DISABLED')
        service.generate_flow_cookie_opening = no_effect
        print(f'UI fixture http://127.0.0.1:{server.server_address[1]} — no real Flow account or dispatch',flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
