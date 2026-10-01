from pathlib import Path

path = Path('C:/Users/JIN/Documents/ChatGPT/DFM/DFM-Project/app.py')
source = path.read_text(encoding='utf-8')
start = source.index('if tab=="설계 조치" or tab is None:')
end = source.index('elif tab=="방향 비교":', start)
replacement = '''if tab=="설계 조치" or tab is None:
    from amdfm.action_view import render_actions
    render_actions(model,report,profile,recommendation,on_apply=apply_orientation,presets=directions,
                   on_navigate=navigate_result,criterion_controls=lambda:render_wall_criterion(process,profile),
                   detail_runner=run_detail)
'''
path.write_text(source[:start] + replacement + source[end:], encoding='utf-8')
