const state = {
  view: 'home', projects: [], project: null, snapshot: null, settings: null,
  busy: false, busyLabel: '', error: null, lastAction: null, runToken: null,
  wizard: null, creationDefaults: null, nextDraftId: 0
};

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const clone = value => JSON.parse(JSON.stringify(value));
const assetUrl = (projectId, path) => `/api/projects/${encodeURIComponent(projectId)}/asset?path=${encodeURIComponent(path)}`;

async function api(path, options = {}) {
  const response = await fetch(path, { headers: {'Content-Type':'application/json'}, ...options });
  let value = {};
  try { value = await response.json(); } catch (_) { value = {}; }
  if (!response.ok) {
    const error = new Error(value.error || 'Story Auto could not complete that action.');
    error.payload = value;
    throw error;
  }
  return value;
}

function toast(message, isError = false) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.toggle('is-error', isError);
  element.classList.add('is-visible');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('is-visible'), 3200);
}

function setBusy(value, label = '') {
  state.busy = value;
  state.busyLabel = label;
  $('#view').setAttribute('aria-busy', String(value));
  document.querySelector('.loading-line')?.remove();
  if (value) document.body.insertAdjacentHTML('beforeend', '<div class="loading-line" aria-hidden="true"></div>');
  $('#runtimeState').textContent = value ? 'Working' : 'Ready';
}

function setHeader(eyebrow, title, actions = '') {
  $('#viewEyebrow').textContent = eyebrow;
  $('#viewTitle').textContent = title;
  $('#appBarActions').innerHTML = actions;
}

function setNav(active) {
  for (const [id, name] of [['homeNav','home'],['settingsNav','settings']]) {
    const item = $(`#${id}`);
    item.classList.toggle('is-active', name === active);
    if (name === active) item.setAttribute('aria-current','page'); else item.removeAttribute('aria-current');
  }
}

function focusMain() {
  window.scrollTo({top:0,left:0,behavior:'instant'});
  requestAnimationFrame(() => $('#mainContent').focus({preventScroll:true}));
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds === '' || !Number.isFinite(Number(seconds))) return 'Estimated after voice';
  const total = Math.round(Number(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2,'0')}`;
}

function formatUpdated(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Recently updated';
  const seconds = Math.max(0, (Date.now() - date.valueOf()) / 1000);
  if (seconds < 90) return 'Updated just now';
  if (seconds < 3600) return `Updated ${Math.round(seconds/60)} min ago`;
  if (seconds < 86400) return `Updated ${Math.round(seconds/3600)} hr ago`;
  if (seconds < 604800) return `Updated ${Math.round(seconds/86400)} day${seconds < 172800 ? '' : 's'} ago`;
  return `Updated ${date.toLocaleDateString(undefined,{month:'short',day:'numeric',year:date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric'})}`;
}

function humanMode(mode) { return mode === 'full_video_ai' ? 'Full video animation' : mode === 'ambient_story' ? 'Ambient Story' : mode === 'full_image' ? 'Full Image' : 'Cinematic opening'; }
function humanAmbientStyle(style) { return style === 'hidden_mastery' ? 'Hidden Mastery' : 'Quiet Verdict'; }
function chipClass(project) { return project.attention?.length ? 'attention' : project.user_status === 'Complete' ? 'success' : ''; }

async function loadProjects() {
  const value = await api('/api/projects');
  state.projects = value.projects || [];
  return state.projects;
}

function projectCard(project) {
  const action = project.primary_action || {action:'Open project', action_id:'open'};
  const directFinal = action.action_id === 'open_final' && project.final_path;
  const primary = directFinal
    ? `<a class="button button-primary" href="${assetUrl(project.project_id,project.final_path)}" target="_blank" rel="noopener">Open final video</a>`
    : `<button class="button-primary" type="button" data-project-action="${esc(action.action_id)}" data-project="${esc(project.project_id)}">${esc(action.action)}</button>`;
  return `<article class="project-card ${project.attention?.length ? 'is-attention' : ''}">
    <div class="card-top"><div><h3>${esc(project.title)}</h3><p class="meta">${esc(formatUpdated(project.updated_at))} · ${esc(humanMode(project.render_mode))}${project.ambient_style_label ? ` · ${esc(project.ambient_style_label)}` : ''}</p></div><span class="status-chip ${chipClass(project)}">${esc(project.user_status)}</span></div>
    <div class="card-progress"><small>${esc(project.current_activity)}</small><strong>${Number(project.progress || 0)}%</strong><div class="progress-track" role="progressbar" aria-label="${esc(project.title)} progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(project.progress || 0)}"><span style="width:${Number(project.progress || 0)}%"></span></div></div>
    <div class="card-actions"><button class="text-button" type="button" data-open-project="${esc(project.project_id)}">View project</button>${primary}</div>
  </article>`;
}

function bindProjectCards() {
  document.querySelectorAll('[data-open-project]').forEach(button => button.addEventListener('click', () => openProject(button.dataset.openProject)));
  document.querySelectorAll('[data-project-action]').forEach(button => button.addEventListener('click', async () => {
    await openProject(button.dataset.project, false);
    await handleProjectAction(button.dataset.projectAction);
  }));
}

async function showHome(announce = false) {
  state.view = 'home'; state.project = null; state.snapshot = null; state.error = null;
  setNav('home');
  setHeader('YOUR VIDEOS','Home','<button class="button-primary" id="newVideoTop" type="button">＋ New video</button>');
  $('#newVideoTop').addEventListener('click', openWizard);
  const view = $('#view');
  view.innerHTML = '<div class="empty-library"><p>Loading your videos…</p></div>';
  try { await loadProjects(); } catch (error) {
    view.innerHTML = errorCard(friendlyError(error)); bindErrorActions(); return;
  }
  const attention = state.projects.filter(project => project.attention?.length);
  const recent = state.projects.filter(project => !project.attention?.length);
  view.innerHTML = `<section class="hero">
    <div><p class="eyebrow">CONTENT TO FINISHED VIDEO</p><h2>Turn your story or narration into a finished video.</h2><p>Start with story text, existing narration audio, or matching audio and SRT. Story Auto guides production from source to final review.</p><button class="button-primary" id="newVideoHero" type="button">＋ New video</button></div>
    <div class="hero-art" aria-hidden="true"></div>
  </section>
  ${attention.length ? `<section class="section"><div class="section-title"><div><h2>Needs your attention</h2><p>${attention.length} project${attention.length === 1 ? '' : 's'} waiting for you.</p></div></div><div class="project-grid">${attention.map(projectCard).join('')}</div></section>` : ''}
  <section class="section"><div class="section-title"><div><h2>${state.projects.length ? 'Recent videos' : 'Your videos'}</h2><p>${state.projects.length ? 'Continue where you left off or open a finished video.' : 'Your projects will appear here.'}</p></div></div>
    ${state.projects.length ? `<div class="project-grid">${recent.concat(attention.length ? [] : attention).map(projectCard).join('') || '<div class="empty-library"><p>Projects needing attention are shown above.</p></div>'}</div>` : '<div class="empty-library"><h2>No videos yet</h2><p>Start with approved narration. Story Auto will keep every completed stage safe as production moves forward.</p><button class="button-primary" id="newVideoEmpty" type="button">Create your first video</button></div>'}
  </section>`;
  ['newVideoTop','newVideoHero','newVideoEmpty'].forEach(id => $(`#${id}`)?.addEventListener('click', openWizard));
  bindProjectCards();
  if (announce) toast('Home');
  focusMain();
}

async function openProject(projectId, moveFocus = true) {
  state.view = 'project'; state.project = projectId; state.error = null;
  setNav('home'); setBusy(true,'Opening project');
  try { state.snapshot = await api(`/api/projects/${encodeURIComponent(projectId)}/snapshot`); setBusy(false); renderProject(); }
  catch (error) { setHeader('PROJECT','Could not open project'); $('#view').innerHTML = errorCard(friendlyError(error)); bindErrorActions(); }
  finally { if (state.busy) setBusy(false); }
  if (moveFocus) focusMain();
}

function stageMarkup(snapshot) {
  const stages = ['Voice','Plan','Create visuals','Quality check','Render','Finish'];
  const current = Math.max(0, stages.indexOf(snapshot.current_stage));
  return `<ol class="stage-list" aria-label="Production stages">${stages.map((label,index) => `<li class="${snapshot.progress === 100 || index < current ? 'is-done' : index === current ? 'is-current' : ''}" ${index === current && snapshot.progress < 100 ? 'aria-current="step"' : ''}>${esc(label)}</li>`).join('')}</ol>`;
}

function executionControls(snapshot) {
  const labels = {FULL:'Full pipeline',EXISTING_VOICE:'Use existing voice / Skip TTS',VISUALS_ONLY:'Visuals only',RENDER_ONLY:'Render only'};
  const policy = snapshot.execution_policy || {};
  return `<section class="surface"><div class="surface-head"><div><h2>Execution / Reuse</h2><p>What Story Auto will do next: ${esc(labels[snapshot.execution_mode] || snapshot.execution_mode)}. Narration is ${esc(snapshot.narration_source || 'GENERATE')}.</p></div></div><div class="choice-grid">${Object.entries(labels).map(([mode,label]) => { const item=policy[mode === 'FULL' ? 'audio' : mode === 'RENDER_ONLY' ? 'visuals' : 'audio']; const unavailable=mode === 'RENDER_ONLY' ? !snapshot.accepted_visuals : mode !== 'FULL' ? !snapshot.duration_seconds : false; const reason=mode === 'RENDER_ONLY' ? 'No accepted visual assets are available for the current plan.' : 'No narration audio has been selected.'; return `<div class="choice"><strong>${esc(label)}</strong><small>${unavailable ? esc(reason) : mode === snapshot.execution_mode ? 'Current execution intent.' : 'Available for this project.'}</small><button data-execution-mode="${mode}" type="button" ${unavailable || mode === snapshot.execution_mode ? 'disabled' : ''}>${mode === snapshot.execution_mode ? 'Selected' : 'Use this mode'}</button></div>`; }).join('')}</div></section>`;
}

function timingControls(snapshot) {
  if (snapshot.narration_audio === 'MISSING' && snapshot.subtitle_timing === 'MISSING') return '';
  const srt = snapshot.subtitle_timing || 'MISSING', timing = snapshot.timing_source || 'MISSING';
  const ttsSkipped = timing === 'SRT' || snapshot.narration_source === 'IMPORTED';
  const planning = snapshot.visual_planning?.status === 'NEEDS_REGENERATION' ? 'BLOCKED' : (snapshot.duration_seconds ? 'READY' : 'BLOCKED');
  return `<section class="surface"><div class="surface-head"><div><h2>Audio and subtitle timing</h2><p>Audio=${esc(snapshot.narration_audio || 'MISSING')} · SRT=${esc(srt)} · TIMING SOURCE=${esc(timing)}</p></div></div><div class="choice-grid"><div class="choice"><strong>TTS = ${ttsSkipped ? 'SKIPPED' : 'REUSE/SKIP'}</strong><small>${timing === 'SRT' ? 'SRT is the canonical timing source; no TTS request will run.' : ttsSkipped ? 'Imported narration is canonical; no TTS request will run.' : 'Narration reuse is validated before downstream work.'}</small></div><div class="choice"><strong>Visual planning = ${planning}</strong><small>Visuals = ${snapshot.accepted_visuals ? 'REUSE' : 'GENERATE'} · Render = ${snapshot.duration_seconds ? 'READY' : 'BLOCKED'}.</small></div></div></section>`;
}

function fullImageRenderControls(snapshot) {
  if (snapshot.render_mode !== 'full_image' || !snapshot.full_image) return '';
  const waveform = snapshot.full_image.audio_visualizer !== false;
  const status = snapshot.render_stale ? 'Waveform changed. Render final video to apply it; narration, planning, and visuals remain reused.' : 'This applies only to the final render. It does not regenerate narration or visuals.';
  return `<section class="surface"><div class="surface-head"><div><h2>Full Image render settings</h2><p>${esc(status)}</p></div></div><fieldset class="field"><legend>Waveform</legend><label class="choice"><input id="fullImageWaveformToggle" type="checkbox" ${waveform ? 'checked' : ''}><strong>Show audio visualizer</strong><small>Applies to this project’s final video only.</small></label></fieldset><div class="button-row"><button id="saveFullImageWaveform" type="button">Save render setting</button></div></section>`;
}

function existingProjectControls(snapshot) {
  const full = snapshot.full_image || {};
  const canRender = !!snapshot.accepted_visuals;
  const visualAction = snapshot.primary_action?.action_id === 'resume_generation' ? 'Continue visuals' : snapshot.primary_action?.action_id === 'process' ? 'Plan visuals' : snapshot.primary_action?.action || 'Plan visuals';
  const visualActionId = snapshot.primary_action?.action_id || 'plan_visuals';
  return `<section class="surface"><div class="surface-head"><div><h2>Visuals and render controls</h2><p>Narration: ${esc(snapshot.narration_audio || 'MISSING')} · Timing: ${esc(snapshot.timing_source || 'MISSING')} · Full Image duration: ${full.image_duration_seconds ? `${esc(full.image_duration_seconds)} sec` : 'Not selected'} · Waveform: ${full.audio_visualizer === false ? 'OFF' : 'ON'}.</p></div></div><div class="choice-grid"><div class="choice"><strong>Generate / Continue visuals</strong><small>${esc(snapshot.duration_seconds ? 'Uses the current canonical narration and timing source.' : 'Blocked: import or generate valid narration first.')}</small><button data-project-action="${esc(visualActionId)}" type="button" ${snapshot.duration_seconds ? '' : 'disabled'}>${esc(visualAction)}</button></div><div class="choice"><strong>Render Again</strong><small>${canRender ? 'Provider-free: reuses the currently accepted visual assets.' : 'Blocked: No accepted visual assets are available for the current plan.'}</small><button data-project-action="render_again" type="button" ${canRender ? '' : 'disabled'}>Render Again</button></div></div></section>`;
}

async function setExecutionMode(mode) {
  try { const value=await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'set_execution_mode',mode})}); state.snapshot=value; renderProject(); toast('Execution intent saved.'); }
  catch (error) { toast(friendlyError(error).message,true); }
}

async function setFullImageAudioVisualizer(enabled) {
  try {
    const value=await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'set_full_image_audio_visualizer',enabled})});
    state.snapshot=value; renderProject(); toast('Render setting saved.');
  } catch (error) { toast(friendlyError(error).message,true); }
}

function projectHeader(snapshot) {
  setHeader('PROJECT', snapshot.title, '<button class="button-quiet" id="backHome" type="button">← Home</button>');
  $('#backHome').addEventListener('click', () => showHome(true));
}

function renderProject() {
  const snapshot = state.snapshot;
  projectHeader(snapshot);
  if (snapshot.progress === 100 && !snapshot.attention?.length) { renderComplete(snapshot); return; }
  const attention = snapshot.attention?.[0];
  const currentActivity = state.busy ? state.busyLabel : snapshot.current_activity;
  $('#view').innerHTML = `<section class="project-hero">
    <div><span class="status-chip ${chipClass(snapshot)}">${esc(snapshot.user_status)}</span><h2>${esc(snapshot.title)}</h2><p>${esc(currentActivity)}</p>
      <div class="project-facts"><div class="fact"><small>Narration</small><strong>${snapshot.word_count ? `${snapshot.word_count.toLocaleString()} words` : 'Needs content'}</strong></div><div class="fact"><small>Narrator</small><strong>${esc(snapshot.narrator?.name || 'Not configured')}</strong></div><div class="fact"><small>Duration</small><strong>${esc(formatDuration(snapshot.duration_seconds))}</strong></div><div class="fact"><small>Style</small><strong>${esc(humanMode(snapshot.render_mode))}</strong></div></div>
      ${stageMarkup(snapshot)}
    </div>
    <div class="progress-panel"><div class="progress-value"><span>Overall progress</span><strong>${Number(snapshot.progress)}%</strong></div><div class="progress-track" role="progressbar" aria-label="Overall production progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(snapshot.progress)}"><span style="width:${Number(snapshot.progress)}%"></span></div><p>${esc(currentActivity)}</p></div>
  </section>
  ${state.error ? errorCard(state.error) : ''}
  ${executionControls(snapshot)}
  ${timingControls(snapshot)}
  ${existingProjectControls(snapshot)}
  ${fullImageRenderControls(snapshot)}
  ${attention ? `<section class="attention-card" aria-labelledby="attentionTitle"><div><h2 id="attentionTitle">${esc(attention.title)}</h2><p>${esc(attention.message)}</p><p class="reassurance">Your completed work is saved.</p></div><div class="button-row"><button class="button-primary" data-project-action="${esc(attention.action_id)}" type="button">${esc(attention.action)}</button>${attention.code === 'FLOW_AUTH_REQUIRED' ? '<button data-project-action="review_project" type="button">Continue recovery</button>' : ''}</div><details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(attention.code)}${snapshot.visual_planning?.failure_class ? `\n${esc(snapshot.visual_planning.failure_class)}` : ''}</div></details></section>` : `<section class="surface next-action"><div><h2>${esc(snapshot.primary_action.action)}</h2><p>${snapshot.work_saved ? 'Completed stages are saved, so Resume continues from the next unfinished step.' : esc(snapshot.current_activity)}</p>${state.busy ? '<p class="hint" id="busyReason">This may take several minutes. You can keep this window open.</p>' : ''}</div><button class="button-primary" data-project-action="${esc(snapshot.primary_action.action_id)}" type="button" ${state.busy ? 'disabled aria-describedby="busyReason"' : ''}>${state.busy ? 'Working…' : esc(snapshot.primary_action.action)}</button></section>`}
  <section class="surface"><div class="surface-head"><div><h2>Project overview</h2><p>Review the result when it is ready, or open technical detail when you need it.</p></div><div class="button-row"><button id="reviewProject" type="button">Review</button>${snapshot.current_stage === 'Create visuals' && !snapshot.final_path ? '<button id="pauseProject" type="button">Pause safely</button>' : ''}</div></div>
    <details class="disclosure" id="projectDetails"><summary>Show details</summary><div id="technicalContent" class="technical">Technical details load only when opened.</div></details>
  </section>`;
  document.querySelectorAll('[data-project-action]').forEach(button => button.addEventListener('click', () => handleProjectAction(button.dataset.projectAction)));
  document.querySelectorAll('[data-execution-mode]').forEach(button => button.addEventListener('click', () => setExecutionMode(button.dataset.executionMode)));
  $('#saveFullImageWaveform')?.addEventListener('click', () => setFullImageAudioVisualizer($('#fullImageWaveformToggle').checked));
  $('#reviewProject')?.addEventListener('click', showReview);
  $('#pauseProject')?.addEventListener('click', requestPause);
  bindErrorActions();
  bindDiagnosticsDisclosure();
}

function renderComplete(snapshot) {
  $('#view').innerHTML = `<section class="success-banner"><p class="eyebrow">VIDEO COMPLETE</p><h2>Your final video is ready.</h2><p>Story Auto finished the production and kept the project files available for review.</p></section>
  <section class="surface review-layout"><div>${snapshot.final_path ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,snapshot.final_path)}" aria-label="Final video preview"></video>` : '<div class="video-frame"></div>'}</div>
    <aside class="review-sidebar"><span class="status-chip success">Complete</span><h3>${esc(snapshot.title)}</h3><p>${esc(formatDuration(snapshot.duration_seconds))} · ${esc(humanMode(snapshot.render_mode))}</p><p>Publishing package: <strong>${snapshot.publishing_status === 'READY' ? 'Ready' : 'Not prepared'}</strong></p><div class="button-row"><a class="button button-primary" href="${assetUrl(snapshot.project_id,snapshot.final_path)}" target="_blank" rel="noopener">Open final video</a><button id="openFolder" type="button">Open folder</button></div></aside>
  </section>
  <section class="surface next-action"><div><h2>Review or start another</h2><p>Inspect quality checks and publishing copy, or begin a new video.</p></div><div class="button-row">${snapshot.execution_mode === 'RENDER_ONLY' ? '<button class="button-primary" id="renderAgain" type="button">Render again</button>' : ''}<button id="reviewComplete" type="button">Review</button><button id="createAnother" type="button">Create another video</button></div></section>
  ${executionControls(snapshot)}
  ${timingControls(snapshot)}
  ${fullImageRenderControls(snapshot)}
  <section class="surface"><details class="disclosure" id="projectDetails"><summary>Show details</summary><div id="technicalContent" class="technical">Technical details load only when opened.</div></details></section>`;
  $('#openFolder').addEventListener('click', () => runAction('open_output','Opening the output folder…'));
  $('#renderAgain')?.addEventListener('click', () => runAction('render_again','Rendering the final video…'));
  $('#reviewComplete').addEventListener('click', showReview);
  $('#createAnother').addEventListener('click', openWizard);
  document.querySelectorAll('[data-execution-mode]').forEach(button => button.addEventListener('click', () => setExecutionMode(button.dataset.executionMode)));
  $('#saveFullImageWaveform')?.addEventListener('click', () => setFullImageAudioVisualizer($('#fullImageWaveformToggle').checked));
  bindDiagnosticsDisclosure();
}

function bindDiagnosticsDisclosure() {
  const details = $('#projectDetails');
  if (!details) return;
  details.addEventListener('toggle', async () => {
    if (!details.open || details.dataset.loaded) return;
    details.dataset.loaded = 'true';
    try {
      const value = await api(`/api/projects/${encodeURIComponent(state.project)}/diagnostics`);
      $('#technicalContent').textContent = JSON.stringify(value,null,2);
    } catch (error) { $('#technicalContent').textContent = friendlyError(error).message; }
  });
}

async function handleProjectAction(action) {
  if (action === 'edit_content') return showContentEditor();
  if (action === 'review_plan') return showPlanReview();
  if (action === 'settings') return showSettings();
  if (action === 'review_visuals' || action === 'review_project' || action === 'open_final') return showReview();
  if (action === 'process') return runAction('process','Creating voice and planning your story…');
  if (action === 'plan_visuals') return runAction('plan_visuals','Preparing the visual plan…');
  if (action === 'resume_generation') return runAction('resume_generation','Creating visuals. Completed work remains saved…');
  if (action === 'render') return runAction('render','Rendering the final video…');
  if (action === 'open_flow_sign_in') return runAction('open_flow_sign_in','Opening the Story Auto Flow sign-in window…');
}

async function runAction(action, label) {
  if (!state.project) return;
  if (state.busy || state.runToken) { toast('Another project action is still running.'); return; }
  const projectId = state.project;
  const token = Symbol(action); state.runToken = token; state.lastAction = {action,label};
  setBusy(true,label); state.error = null; renderProject();
  let polling = false;
  const poll = setInterval(async () => {
    if (state.runToken !== token || polling) return;
    polling = true;
    try {
      const snapshot = await api(`/api/projects/${encodeURIComponent(projectId)}/snapshot`);
      if (state.runToken === token && state.view === 'project' && state.project === projectId) { state.snapshot = snapshot; renderProject(); }
    }
    catch (_) { /* the primary request owns failure reporting */ }
    finally { polling = false; }
  },2500);
  try {
    await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action})});
    const snapshot = await api(`/api/projects/${encodeURIComponent(projectId)}/snapshot`);
    if (state.runToken === token && state.view === 'project' && state.project === projectId) state.snapshot = snapshot;
    toast(action === 'pause' ? 'Production will pause at the next safe point.' : action === 'open_flow_sign_in' ? 'Flow sign-in opened.' : 'Project updated.');
  } catch (error) {
    const friendly = friendlyError(error);
    if (state.runToken === token && state.view === 'project' && state.project === projectId) state.error = friendly;
    toast(friendly.title,true);
  } finally {
    clearInterval(poll);
    const ownsRun = state.runToken === token;
    const stillViewingProject = ownsRun && state.view === 'project' && state.project === projectId;
    if (ownsRun) { state.runToken = null; setBusy(false); }
    if (stillViewingProject) renderProject();
  }
}

async function requestPause() {
  if (!state.project) return;
  const button = $('#pauseProject'); if (button) { button.disabled = true; button.textContent = 'Pausing…'; }
  try {
    await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'pause'})});
    toast('Production will pause at the next safe point.');
    if (!state.busy) { state.snapshot = await api(`/api/projects/${encodeURIComponent(state.project)}/snapshot`); renderProject(); }
  } catch (error) { state.error = friendlyError(error); toast(state.error.title,true); if (!state.busy) renderProject(); }
}

function friendlyError(error) {
  const code = error?.payload?.failure_class || 'UNKNOWN_ERROR';
  const raw = error?.payload?.error || error?.message || code;
  const known = {
    FLOW_AUTH_REQUIRED: ['Google sign-in required','Sign in to Google Flow, then return here and choose Try again.','open_flow_sign_in','Open Flow sign-in'],
    FLOW_CDP_UNAVAILABLE: ['Google Flow is not open','Open the dedicated Story Auto Flow window, sign in if needed, then try again.','open_flow_sign_in','Open Flow sign-in'],
    FLOW_PROJECT_MISMATCH: ['Choose the Story Auto Flow project','Open the configured Story Auto project in Google Flow, then try again.','open_flow_sign_in','Open Flow project'],
    FLOW_CAPABILITY_UNAVAILABLE: ['Visual setup needs attention','Review the Flow project and production mode in Settings before trying again.','settings','Open Settings'],
    TTS_PROVIDER_CREDITS_REQUIRED: ["Voice generation can't continue",'The selected paid voice provider does not have enough credits. Choose another voice or update the provider account.','settings','Open settings'],
    CREDENTIAL_MISSING: ['AI quality is not configured','Add the provider credential in the secure Story Auto configuration, then try again.','settings','Open settings'],
    GEMINI_CREDENTIAL_MISSING: ['AI quality is not configured','Add a Gemini credential in the secure Story Auto configuration, then try again.','settings','Open settings'],
    KOKORO_RUNTIME_NOT_FOUND: ['Local voice is not ready','Set the Kokoro installation location in Advanced settings, or choose an available narrator.','settings','Open settings'],
    KOKORO_MODEL_NOT_FOUND: ['Kokoro model files are missing','Restore the configured local Kokoro model files, then open Settings to verify readiness.','settings','Open settings'],
    KOKORO_VOICE_NOT_FOUND: ['The selected Kokoro voice is missing','Restore the selected local voice file or choose an installed narrator, then try again.','settings','Open settings'],
    KOKORO_RUNTIME_LOAD_FAILED: ['Kokoro could not load its local model','Review Kokoro diagnostics in Settings, correct the local runtime, then try again.','settings','Open settings'],
    KOKORO_CONFIGURATION_INVALID: ['Kokoro settings are invalid','Review the local Kokoro runtime, model snapshot, and narrator settings, then try again.','settings','Open settings'],
    AMBIENT_VISUAL_BRIEF_OVER_BUDGET: ['Visual planning needs to be regenerated','Story Auto kept the narration and audio, but the visual brief must be made more concise before images can be created.','review_plan','Review visual plan'],
    AMBIENT_CHAPTER_HARD_MAX_EXCEEDED: ['Visual planning needs to be regenerated','The story contains more incompatible visual states than this Ambient style can safely support. Review the visual plan before continuing.','review_plan','Review visual plan'],
    PROJECT_LOCKED: ['This project is still working','Story Auto is finishing another saved operation. Wait for it to finish, then refresh the project.','open_project','Refresh project'],
    ArtifactWriteError: ['A saved update needs a brief retry','A temporary local file lock interrupted saving project state. Refresh the project after a moment; this does not send another Flow request.','open_project','Refresh project'],
    IMAGE_ASSET_INVALID: ['Recovered image could not be used','Check that the path points to a readable image downloaded from the matching Flow result.','retry','Try again'],
    VIDEO_ASSET_INVALID: ['Recovered video could not be used','Check that the path points to a readable video downloaded from the matching Flow result.','retry','Try again'],
  };
  const match = known[code] || (code.includes('CREDIT') ? known.TTS_PROVIDER_CREDITS_REQUIRED : null);
  return { code, raw, title: match?.[0] || "Story Auto couldn't continue", message: match?.[1] || 'Review the project details and try again. Your completed work is safe.', action_id: match?.[2] || 'retry', action: match?.[3] || 'Try again' };
}

function errorCard(error) {
  return `<section class="attention-card" role="alert"><div><h2>${esc(error.title)}</h2><p>${esc(error.message)}</p><p class="reassurance">Your completed work is saved.</p></div><button class="button-primary" data-error-action="${esc(error.action_id)}" type="button">${esc(error.action)}</button><details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(error.code)}\n${esc(error.raw)}</div></details></section>`;
}

function bindErrorActions() {
  document.querySelectorAll('[data-error-action]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.errorAction;
    if (action === 'settings') return showSettings();
    if (action === 'open_flow_sign_in') return runAction('open_flow_sign_in','Opening the Story Auto Flow sign-in window…');
    if (action === 'retry' && state.lastAction) return runAction(state.lastAction.action,state.lastAction.label);
    return state.project ? openProject(state.project) : showHome();
  }));
}

async function showContentEditor() {
  const content = await api(`/api/projects/${encodeURIComponent(state.project)}/content`);
  setHeader('PROJECT CONTENT',state.snapshot.title,'<button class="button-quiet" id="backProject" type="button">← Project</button>');
  $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><h2>Edit content</h2><p>Story Auto uses the single Narration section as the approved voice script.</p></div></div><div class="field"><label for="projectContent">Content</label><textarea id="projectContent" spellcheck="true">${esc(content.content)}</textarea><small>Include exactly one non-empty <strong>## Narration</strong> section.</small></div><div class="button-row" style="margin-top:18px"><button class="button-primary" id="saveProjectContent" type="button">Save content</button><button id="cancelContent" type="button">Cancel</button></div></section>`;
  $('#backProject').addEventListener('click', () => openProject(state.project));
  $('#cancelContent').addEventListener('click', () => openProject(state.project));
  $('#saveProjectContent').addEventListener('click', async () => {
    try { await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'save_content',content:$('#projectContent').value})}); toast('Content saved.'); await openProject(state.project); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  focusMain();
}

async function showPlanReview() {
  const planning = await api(`/api/projects/${encodeURIComponent(state.project)}/planning`);
  const continuity = planning.continuity_bible || {};
  const shots = planning.shot_plan?.shots || [];
  const approval = planning.review_state?.plan_approval?.status || 'NOT_STARTED';
  const hasVisualPlan = Boolean(planning.shot_plan && planning.media_plan && planning.generation_requests);
  const names = kind => (continuity[kind] || []).map(item => item.name).filter(Boolean);
  setHeader('REVIEW PLAN',state.snapshot.title,'<button class="button-quiet" id="backProject" type="button">← Project</button>');
  $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><p class="eyebrow">BEFORE VISUAL CREATION</p><h2>${hasVisualPlan ? 'Review the visual plan' : 'Review the story plan'}</h2><p>Confirm the story structure before Story Auto begins the next costly stage.</p></div></div>
    <dl class="summary-list"><div class="summary-row"><dt>Characters</dt><dd>${esc(names('characters').join(', ') || 'No recurring characters detected')}</dd></div><div class="summary-row"><dt>Locations</dt><dd>${esc(names('locations').join(', ') || 'No recurring locations detected')}</dd></div><div class="summary-row"><dt>Scenes</dt><dd>${shots.length || planning.story_timeline?.scenes?.length || 0}</dd></div><div class="summary-row"><dt>Production style</dt><dd>${esc(humanMode(state.snapshot.render_mode))}</dd></div></dl>
    <div class="next-action" style="margin-top:22px"><div><h2>${hasVisualPlan ? 'Approve visual plan' : 'Approve and prepare visuals'}</h2><p>${hasVisualPlan ? 'This allows Story Auto to begin creating the planned scenes.' : 'Story Auto will turn this approved story structure into a visual plan.'}</p></div><button class="button-primary" id="approveCurrentPlan" type="button">${hasVisualPlan ? 'Approve visual plan' : 'Approve story plan'}</button></div>
    <details class="disclosure"><summary>Technical plan details</summary><div class="technical">${esc(JSON.stringify({approval,story_timeline:planning.story_timeline,continuity_bible:planning.continuity_bible,shot_plan:planning.shot_plan,media_plan:planning.media_plan},null,2))}</div></details>
  </section>`;
  $('#backProject').addEventListener('click', () => openProject(state.project));
  $('#approveCurrentPlan').addEventListener('click', async () => {
    setBusy(true,hasVisualPlan ? 'Approving the visual plan…' : 'Preparing the visual plan…');
    try {
      if (hasVisualPlan) await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'approve_shots'})});
      else {
        if (approval !== 'APPROVED') await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'approve_plan'})});
        await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'plan_visuals'})});
      }
      toast(hasVisualPlan ? 'Visual plan approved.' : 'Visual plan is ready to review.'); await openProject(state.project);
    } catch (error) { toast(friendlyError(error).message,true); }
    finally { setBusy(false); }
  });
  focusMain();
}

function qualityCards(items) {
  return `<div class="quality-grid">${items.map(item => `<div class="quality-card"><small>${esc(item.label)}</small><strong class="${item.status === 'Passed' ? 'passed' : item.status === 'Needs review' ? 'needs-review' : ''}">${esc(item.status)}</strong></div>`).join('')}</div>`;
}

function qcReport(alignmentClassification = null) {
  const keys = ['SKIN_REALISM','LIGHTING_NATURALISM','MATERIAL_REALISM','COMPOSITION_NATURALISM','AI_POLISH','CONTINUITY','TECHNICAL_VALIDITY'];
  return {results:Object.fromEntries(keys.map(key => [key,'PASS'])),visible_provider_watermark:false,reviewer:'local_operator',notes:'Approved in Story Auto review',...(alignmentClassification ? {alignment_classification:alignmentClassification} : {})};
}

async function showReview() {
  setBusy(true,'Opening review…');
  try {
    const [review, media] = await Promise.all([api(`/api/projects/${encodeURIComponent(state.project)}/review`),api(`/api/projects/${encodeURIComponent(state.project)}/media`)]);
    setHeader('REVIEW',review.title,'<button class="button-quiet" id="backProject" type="button">← Project</button>');
    const byId = new Map([...media.references,...media.shots,...(media.thumbnails || [])].map(item => [item.request.request_id,item]));
    const issues = review.issues.map(issue => {
      const item = byId.get(issue.request_id) || {}; const selected = item.selected_asset;
      const preview = selected ? (issue.media_type === 'VIDEO' ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(state.project,selected.path)}"></video>` : `<img class="video-frame" src="${assetUrl(state.project,selected.path)}" alt="Generated ${esc(issue.label).toLowerCase()}">`) : '';
      const createAgain = ['CREDIT_BLOCKED','FAILED_PERMANENT','CANCELLED','AUTH_REQUIRED'].includes(issue.status);
      const recovery = issue.recovery_action === 'flow_sign_in_then_requeue' ? '<button class="button-primary" data-review-flow type="button">Open Flow sign-in</button>' : issue.recovery_action === 'manual_asset' ? '<button data-recover-file type="button">Use recovered file</button>' : '';
      const recoveryForm = issue.recovery_action === 'manual_asset' ? `<div class="recovery-form" data-recovery-form hidden><div class="field"><label>Recovered file path<input data-recovered-path type="text" autocomplete="off" placeholder="C:\\Downloads\\recovered-visual.png"></label><small>Use the exact image or video downloaded from this Flow result. Story Auto will preserve the original attempt.</small><p class="recovery-error" data-recovery-error role="alert" hidden></p></div><button class="button-primary" data-use-recovered="${esc(issue.request_id)}" type="button">Attach recovered file</button></div>` : '';
      const needsAlignment = item.request?.purpose === 'SHOT';
      const alignmentControl = issue.status === 'QC_PENDING' && needsAlignment ? `<div class="field review-alignment"><label>Scene-to-narration match<select data-alignment="${esc(issue.request_id)}"><option value="" selected disabled>Choose a match verdict</option><option value="PASS_DIRECT">Directly shows this narrated moment</option><option value="PASS_SUPPORTIVE">Supports this narrated moment</option><option value="PASS_ATMOSPHERIC">Atmospheric only</option></select></label><small>Required before approving a scene. Choose atmospheric only when the shot plan allows it.</small></div>` : '';
      const reopen = (issue.failure_class || issue.technical_code) === 'VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED' && selected ? `<button data-reopen-qc="${esc(issue.request_id)}" data-asset-sha="${esc(selected.sha256)}" type="button">Reopen quality review</button>` : '';
      return `<article class="issue">${preview}<h3>${esc(issue.label)}</h3><p>${esc(issue.message)}</p>${alignmentControl}<div class="button-row">${issue.status === 'QC_PENDING' ? `<button class="button-primary" data-approve="${esc(issue.request_id)}" type="button"${needsAlignment ? ' disabled' : ''}>Approve ${esc(issue.label).toLowerCase()}</button>` : ''}${reopen}${recovery}${issue.retryable && !reopen ? `<button data-regenerate="${esc(issue.request_id)}" type="button">${createAgain ? 'Create again' : 'Regenerate'}</button>` : ''}</div>${recoveryForm}<details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(issue.status)}\n${esc(issue.technical_code || issue.request_id)}</div></details></article>`;
    }).join('');
    const publishing = review.publishing || {};
    $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><h2>Quality review</h2><p>${review.final_path ? `Final duration ${esc(formatDuration(review.duration_seconds))}.` : 'Review flagged scenes before production continues.'}</p></div>${review.final_path ? `<a class="button button-primary" href="${assetUrl(state.project,review.final_path)}" target="_blank" rel="noopener">Open final video</a>` : ''}</div>${qualityCards(review.quality)}</section>
      ${review.final_path ? `<section class="surface review-layout"><video class="video-frame" controls preload="metadata" src="${assetUrl(state.project,review.final_path)}" aria-label="Final video review"></video><aside class="review-sidebar"><h3>Publishing package</h3><p><strong>${esc(publishing.selected_title || review.title)}</strong></p><p class="publishing-copy">${esc(publishing.description || 'Publishing copy has not been prepared yet.')}</p>${publishing.description ? '<button id="copyPublishing" type="button">Copy title & description</button>' : ''}</aside></section>` : ''}
      <section class="surface"><div class="surface-head"><div><h2>Items needing review</h2><p>${review.issues.length ? `${review.issues.length} item${review.issues.length === 1 ? ' needs' : 's need'} a decision.` : 'No remaining quality issues were found.'}</p></div></div><div class="issue-list">${issues || '<div class="empty-library"><strong>Quality checks are clear.</strong><p>No item needs your attention.</p></div>'}</div></section>`;
    $('#backProject').addEventListener('click', () => openProject(state.project));
    $('#copyPublishing')?.addEventListener('click', async () => { await navigator.clipboard.writeText(`${publishing.selected_title || review.title}\n\n${publishing.description}`); toast('Title and description copied.'); });
    document.querySelectorAll('[data-alignment]').forEach(select => select.addEventListener('change', () => {
      select.closest('.issue').querySelector('[data-approve]').disabled = !select.value;
    }));
    document.querySelectorAll('[data-approve]').forEach(button => button.addEventListener('click', async () => {
      const projectId=state.project; button.disabled=true;
      const alignment = button.closest('.issue').querySelector('[data-alignment]')?.value || null;
      try { await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action:'approve_asset',request_id:button.dataset.approve,report:qcReport(alignment)})}); toast('Scene approved.'); await showReview(); }
      catch (error) { const friendly=friendlyError(error); state.error=friendly; toast(friendly.title,true); await openProject(projectId); state.error=friendly; renderProject(); }
    }));
    document.querySelectorAll('[data-reopen-qc]').forEach(button => button.addEventListener('click', async () => {
      const projectId=state.project; button.disabled=true;
      try { await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action:'reopen_production_qc',request_id:button.dataset.reopenQc,expected_asset_sha256:button.dataset.assetSha,reviewer:'local_operator',reason:'The prior UI approval omitted the required scene-to-narration verdict; review the same confirmed asset again.'})}); toast('Quality review reopened for the same asset.'); await showReview(); }
      catch (error) { const friendly=friendlyError(error); toast(friendly.title,true); button.disabled=false; }
    }));
    document.querySelectorAll('[data-regenerate]').forEach(button => button.addEventListener('click', async () => {
      const projectId=state.project; button.disabled=true;
      try { await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action:'regenerate',request_id:button.dataset.regenerate})}); toast('Scene queued for regeneration.'); await openProject(projectId); }
      catch (error) { const friendly=friendlyError(error); state.error=friendly; toast(friendly.title,true); await openProject(projectId); state.error=friendly; renderProject(); }
    }));
    document.querySelectorAll('[data-review-flow]').forEach(button => button.addEventListener('click', async () => {
      const projectId=state.project; button.disabled=true;
      try { await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action:'open_flow_sign_in'})}); toast('Complete sign-in, then choose Create again.'); }
      catch (error) { const friendly=friendlyError(error); toast(friendly.title,true); }
      finally { button.disabled=false; }
    }));
    document.querySelectorAll('[data-recover-file]').forEach(button => button.addEventListener('click', () => { const form=button.closest('.issue').querySelector('[data-recovery-form]'); form.hidden=false; button.hidden=true; form.querySelector('[data-recovered-path]').focus(); }));
    document.querySelectorAll('[data-use-recovered]').forEach(button => button.addEventListener('click', async () => {
      const projectId=state.project; const input=button.closest('[data-recovery-form]').querySelector('[data-recovered-path]'); const sourcePath=input.value.trim();
      if (!sourcePath) { toast('Enter the downloaded file path.',true); input.focus(); return; }
      button.disabled=true;
      try { await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action:'replace_asset',request_id:button.dataset.useRecovered,source_path:sourcePath})}); toast('Recovered file attached for quality review.'); await openProject(projectId); }
      catch (error) { const friendly=friendlyError(error); const alert=button.closest('[data-recovery-form]').querySelector('[data-recovery-error]'); alert.textContent=friendly.message; alert.hidden=false; toast(friendly.title,true); button.disabled=false; }
    }));
  } catch (error) { $('#view').innerHTML = errorCard(friendlyError(error)); bindErrorActions(); }
  finally { setBusy(false); }
  focusMain();
}

function savedDefaults() {
  try { return JSON.parse(localStorage.getItem('storyAutoDefaults') || '{}'); } catch (_) { return {}; }
}

function installedVoices() {
  const source = state.creationDefaults || state.settings;
  return Array.isArray(source?.voice_options) ? source.voice_options : [];
}
function hasInstalledVoice(voiceId) { return installedVoices().some(voice => voice.voice_id === voiceId); }
function voiceName(voiceId) { return installedVoices().find(voice => voice.voice_id === voiceId)?.name || voiceId || 'Choose a narrator'; }
function voiceOptions(selectedVoice, placeholder = 'Choose an installed narrator') {
  const options = installedVoices();
  const prompt = `<option value="" ${hasInstalledVoice(selectedVoice) ? '' : 'selected'} disabled>${esc(options.length ? placeholder : 'No installed Kokoro narrators are available')}</option>`;
  return prompt + options.map(voice => `<option value="${esc(voice.voice_id)}" ${voice.voice_id === selectedVoice ? 'selected' : ''}>${esc(voice.name)}</option>`).join('');
}

async function showSettings() {
  state.view = 'settings'; state.project = null; state.snapshot = null; state.error = null;
  setNav('settings'); setHeader('APPLICATION','Settings');
  $('#view').innerHTML = '<div class="empty-library"><p>Loading settings…</p></div>';
  try { state.settings = await api('/api/settings'); } catch (error) { $('#view').innerHTML = errorCard(friendlyError(error)); bindErrorActions(); return; }
  const saved = savedDefaults(); const defaults = {...state.settings.defaults,...saved};
  const selectedDefaultVoice = hasInstalledVoice(defaults.voice_id) ? defaults.voice_id : '';
  const narratorMessage = state.settings.defaults.narrator_message || (installedVoices().length ? '' : 'No installed Kokoro narrators are available. Configure Kokoro before creating a video.');
  const providerRows = state.settings.providers.map(provider => `<div class="provider-row"><div><strong>${esc(provider.name)}</strong><small>${esc(provider.detail)}</small></div><span class="provider-state ${provider.status !== 'Ready' ? 'attention' : ''}">${esc(provider.status)}</span></div>`).join('');
  const projectOptions = state.projects.map(project => `<option value="${esc(project.project_id)}">${esc(project.title)}</option>`).join('');
  $('#view').innerHTML = `<div class="settings-layout">
    <section class="settings-section"><h2>General</h2><p>Defaults are applied to new videos and saved only in this local browser.</p><div class="settings-grid"><div class="field"><label for="defaultMode">Default format</label><select id="defaultMode"><option value="hybrid_hook" ${defaults.render_mode === 'hybrid_hook' ? 'selected' : ''}>Cinematic opening</option><option value="full_video_ai" ${defaults.render_mode === 'full_video_ai' ? 'selected' : ''}>Full video animation</option><option value="ambient_story" ${defaults.render_mode === 'ambient_story' ? 'selected' : ''}>Ambient Story</option><option value="full_image" ${defaults.render_mode === 'full_image' ? 'selected' : ''}>Full Image</option></select></div><div class="field" id="defaultAmbientStyleField" ${defaults.render_mode === 'ambient_story' ? '' : 'hidden'}><label for="defaultAmbientStyle">Default Ambient Story style</label><select id="defaultAmbientStyle"><option value="quiet_verdict" ${defaults.ambient_style !== 'hidden_mastery' ? 'selected' : ''}>Quiet Verdict</option><option value="hidden_mastery" ${defaults.ambient_style === 'hidden_mastery' ? 'selected' : ''}>Hidden Mastery</option></select></div><div class="field"><label for="defaultVoice">Default narrator</label><select id="defaultVoice" ${installedVoices().length ? '' : 'disabled'}>${voiceOptions(selectedDefaultVoice)}</select>${narratorMessage ? `<small class="field-error">${esc(narratorMessage)}</small>` : ''}</div></div><div class="button-row" style="margin-top:18px"><button class="button-primary" id="saveDefaults" type="button" ${installedVoices().length ? '' : 'disabled'}>Save defaults</button></div></section>
    <section class="settings-section"><h2>Provider health</h2><p>Concise readiness based on this workspace's current configuration and project state.</p><div class="provider-list">${providerRows}</div></section>
    <section class="settings-section"><h2>Storage</h2><p>Story Auto keeps projects and generated media in its isolated local workspace.</p><dl class="summary-list"><div class="summary-row"><dt>Project location</dt><dd>${esc(state.settings.storage.project_location)}</dd></div><div class="summary-row"><dt>Free space</dt><dd>${state.settings.storage.free_gb} GB</dd></div></dl></section>
    <section class="settings-section"><h2>Advanced</h2><p>Technical configuration and diagnostics for troubleshooting.</p><details class="disclosure"><summary>Provider details</summary><dl class="summary-list"><div class="summary-row"><dt>Voice provider</dt><dd>${esc(state.settings.advanced.tts_provider)}</dd></div>${state.settings.advanced.kokoro_readiness ? `<div class="summary-row"><dt>Kokoro readiness</dt><dd>${esc(state.settings.advanced.kokoro_readiness.technical_code || state.settings.advanced.kokoro_readiness.state)}</dd></div>` : ''}<div class="summary-row"><dt>Gemini model</dt><dd>${esc(state.settings.advanced.gemini_model)}</dd></div><div class="summary-row"><dt>Flow project</dt><dd>${esc(state.settings.advanced.flow_project)}</dd></div><div class="summary-row"><dt>Runtime root</dt><dd>${esc(state.settings.advanced.runtime_root)}</dd></div></dl></details>
      <details class="disclosure"><summary>Diagnostics</summary><div class="field"><label for="diagnosticProject">Project</label><select id="diagnosticProject">${projectOptions || '<option value="">No projects available</option>'}</select><small>Diagnostics may include internal IDs, exact paths, manifests, provider attempts, and raw status codes.</small></div><button id="openDiagnostics" type="button" style="margin-top:14px" ${projectOptions ? '' : 'disabled'}>Open diagnostics</button></details>
    </section>
  </div>`;
  $('#defaultMode').addEventListener('change', () => { $('#defaultAmbientStyleField').hidden = $('#defaultMode').value !== 'ambient_story'; });
  $('#saveDefaults').addEventListener('click', () => { const voiceId=$('#defaultVoice').value; if (!hasInstalledVoice(voiceId)) { toast('Choose an installed narrator before saving defaults.',true); return; } localStorage.setItem('storyAutoDefaults',JSON.stringify({render_mode:$('#defaultMode').value,ambient_style:$('#defaultAmbientStyle').value,voice_id:voiceId})); toast('Defaults saved.'); });
  $('#openDiagnostics')?.addEventListener('click', () => showDiagnostics($('#diagnosticProject').value));
  focusMain();
}

async function showDiagnostics(projectId) {
  if (!projectId) return;
  setHeader('SETTINGS / ADVANCED','Diagnostics','<button class="button-quiet" id="backSettings" type="button">← Settings</button>');
  $('#view').innerHTML = '<div class="empty-library"><p>Loading diagnostics…</p></div>';
  try {
    const value = await api(`/api/projects/${encodeURIComponent(projectId)}/diagnostics`);
    $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><h2>Project diagnostics</h2><p>Engineering detail is separated from the normal production workflow.</p></div></div><div class="technical">${esc(JSON.stringify(value,null,2))}</div></section>`;
  } catch (error) { $('#view').innerHTML = errorCard(friendlyError(error)); bindErrorActions(); }
  $('#backSettings').addEventListener('click', showSettings);
  focusMain();
}

function sourceLabel(source) { return ({STORY_CONTENT:'Story / Content',EXISTING_AUDIO:'Existing Audio',AUDIO_SRT:'Audio + SRT'})[source] || source; }
function sourceExecution(source) { return source === 'STORY_CONTENT' ? 'FULL' : 'EXISTING_VOICE'; }
function freshDraft() {
  const saved = savedDefaults();
  return {
    id: ++state.nextDraftId, revision: 0, step: 1, source: 'STORY_CONTENT', content: '', info: null,
    voice: saved.voice_id || '', style: 'natural', mode: saved.render_mode || 'hybrid_hook', execution: 'FULL',
    importedAudio: null, importedSrt: null, sourceValidation: null, ambientStyle: saved.ambient_style || 'quiet_verdict',
    fullImage: saved.full_image || {image_duration_seconds:30, cadence:'SEMANTIC_ADAPTIVE', motion:'AUTO_CONTINUOUS_ZOOM', audio_visualizer:true},
    touched: {}, creating: false,
  };
}
function activeDraft(draft) { return state.wizard === draft; }
function draftBinding(draft) { return {id:draft.id, revision:draft.revision, source:draft.source, audio:draft.importedAudio, srt:draft.importedSrt}; }
function bindingIsCurrent(draft, binding) {
  return activeDraft(draft) && draft.id === binding.id && draft.revision === binding.revision &&
    draft.source === binding.source && draft.importedAudio === binding.audio && draft.importedSrt === binding.srt;
}
function touchDraft(draft, field) { draft.touched[field] = true; draft.revision += 1; }
function hydrateDraftDefaults(draft, payload) {
  if (!activeDraft(draft)) return;
  state.creationDefaults = payload;
  const defaults = payload.defaults || {};
  if (!draft.touched.voice && !draft.voice) draft.voice = defaults.voice_id || '';
  if (!draft.touched.mode && !draft.mode) draft.mode = defaults.render_mode || 'hybrid_hook';
  if (!draft.touched.ambientStyle && !draft.ambientStyle) draft.ambientStyle = defaults.ambient_style || 'quiet_verdict';
}
async function hydrateCreationDefaults(draft) {
  try {
    const payload = await api('/api/creation-defaults');
    if (!activeDraft(draft)) return;
    hydrateDraftDefaults(draft, payload);
    if ($('#newVideoDialog').open) renderWizard();
  } catch (_) {
    // The shell remains usable. Execution-time validation still fails closed.
  }
}
function sourceStatusMarkup(wizard) {
  if (wizard.source === 'STORY_CONTENT') return '<p class="hint">Add approved narration text. Story Auto will generate narration with the selected voice.</p>';
  if (wizard.source === 'EXISTING_AUDIO' && !wizard.importedAudio) return '<p class="hint">Audio: BLOCKED — choose a readable narration file. TTS will be skipped.</p>';
  if (wizard.source === 'AUDIO_SRT' && (!wizard.importedAudio || !wizard.importedSrt)) return `<p class="hint">Audio: ${wizard.importedAudio ? 'selected' : 'BLOCKED — required'} · SRT: ${wizard.importedSrt ? 'selected' : 'BLOCKED — required'}. Create remains unavailable until both files validate.</p>`;
  if (wizard.sourceValidation?.status === 'PASS') return `<p class="hint">Audio: PASS · ${wizard.source === 'AUDIO_SRT' ? 'SRT: PASS · TIMING: SRT' : 'TIMING: ALIGNMENT'} · TTS: SKIPPED</p>`;
  if (wizard.sourceValidation?.status === 'FAIL') return `<p class="hint">Validation: BLOCKED — ${esc(wizard.sourceValidation.reason)}</p>`;
  return '<p class="hint">Files selected. Continue to validate them before configuring the video.</p>';
}
async function readBrowserImport(event, property) {
  const file=event.target.files?.[0]; if (!file) return;
  const wizard=state.wizard;
  if (!wizard) return;
  const encoded=await new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=() => resolve(String(reader.result).split(',')[1] || ''); reader.onerror=reject; reader.readAsDataURL(file); });
  if (!activeDraft(wizard)) return;
  wizard[property]={filename:file.name,base64:encoded}; wizard.sourceValidation=null; touchDraft(wizard,property); renderWizard();
  const ready=wizard.source === 'EXISTING_AUDIO' ? !!wizard.importedAudio : wizard.source === 'AUDIO_SRT' ? !!wizard.importedAudio && !!wizard.importedSrt : false;
  if (ready) { try { await validateSourceImports(wizard); } catch (_) {} if (activeDraft(wizard)) renderWizard(); }
}
async function validateSourceImports(wizard=state.wizard) {
  if (!wizard) return null;
  const binding=draftBinding(wizard);
  try {
    const value=await api('/api/validate-imports',{method:'POST',body:JSON.stringify({source_mode:wizard.source,imported_audio:wizard.importedAudio,imported_srt:wizard.importedSrt})});
    if (!bindingIsCurrent(wizard,binding)) return null;
    wizard.sourceValidation=value; return value;
  } catch (error) {
    if (!bindingIsCurrent(wizard,binding)) return null;
    wizard.sourceValidation={status:'FAIL',reason:friendlyError(error).message}; throw error;
  }
}

async function openWizard() {
  const isNew = !state.wizard;
  if (isNew) state.wizard = freshDraft();
  const wizard=state.wizard;
  renderWizard();
  if (!$('#newVideoDialog').open) $('#newVideoDialog').showModal();
  focusWizardStep();
  if (isNew) hydrateCreationDefaults(wizard);
}

function wizardSteps() {
  const labels = ['Input source','Format & output','Review & Create'];
  return labels.map((label,index) => `<li class="${index + 1 < state.wizard.step ? 'is-done' : index + 1 === state.wizard.step ? 'is-current' : ''}" ${index + 1 === state.wizard.step ? 'aria-current="step"' : ''}>${index + 1}. ${label}</li>`).join('');
}

function showWizardError(message, fieldId = '') {
  const error = $('#wizardError');
  error.textContent = message; error.hidden = !message;
  document.querySelectorAll('[aria-invalid="true"]').forEach(field => { field.removeAttribute('aria-invalid'); field.removeAttribute('aria-describedby'); });
  const field = fieldId ? $(`#${fieldId}`) : null;
  if (message && field) { field.setAttribute('aria-invalid','true'); field.setAttribute('aria-describedby','wizardError contentHelp'); }
}

function focusWizardStep() {
  requestAnimationFrame(() => {
    const target = state.wizard.step === 1 ? $('#sourceStory') : state.wizard.step === 2 ? $('#fullImageDuration') || $('#formatChoice') : $('#wizardTitle');
    target?.focus();
  });
}

function renderWizard() {
  const wizard = state.wizard;
  $('#wizardSteps').innerHTML = wizardSteps(); showWizardError('');
  const title = wizard.step === 1 ? 'Choose your input source' : wizard.step === 2 ? 'Choose format and output' : 'Review and create';
  $('#wizardTitle').textContent = title;
  if (wizard.step === 1) {
    const fields = wizard.source === 'STORY_CONTENT'
      ? `<div class="file-drop"><label class="field-label" for="contentFile">Choose an approved content package or content.md</label><input id="contentFile" type="file" accept=".md,.txt,text/markdown,text/plain"><p class="hint">The file stays on this computer and is read into the project when you create it.</p></div><div class="field" style="margin-top:18px"><label for="contentInput">Content</label><textarea id="contentInput" spellcheck="true" placeholder="# Story title\n\n## Narration\n\nPaste approved narration here.">${esc(wizard.content)}</textarea><small id="contentHelp">Story Auto checks for one non-empty Narration section.</small></div>`
      : wizard.source === 'EXISTING_AUDIO'
        ? `<div class="file-drop"><label class="field-label" for="existingAudio">Narration audio</label><input id="existingAudio" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/flac,audio/ogg,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"><p class="hint">${wizard.importedAudio ? `Selected: ${esc(wizard.importedAudio.filename)}.` : 'Choose a readable narration file.'} TTS will be skipped.</p></div><div class="field" style="margin-top:18px"><label for="contentInput">Canonical narration text</label><textarea id="contentInput" spellcheck="true" placeholder="# Narration source\n\n## Narration\n\nPaste the narration spoken in this audio.">${esc(wizard.content)}</textarea><small id="contentHelp">Needed to plan visuals truthfully when no SRT timing is supplied.</small></div>`
        : `<div class="file-drop"><label class="field-label" for="existingAudio">Narration audio</label><input id="existingAudio" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/flac,audio/ogg,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"><p class="hint">${wizard.importedAudio ? `Selected: ${esc(wizard.importedAudio.filename)}.` : 'Required.'}</p></div><div class="file-drop" style="margin-top:18px"><label class="field-label" for="existingSrt">Matching SRT timing</label><input id="existingSrt" type="file" accept=".srt,text/plain"><p class="hint">${wizard.importedSrt ? `Selected: ${esc(wizard.importedSrt.filename)}.` : 'Required.'} Its text becomes the canonical project narration; no content.md is required from you.</p></div>`;
    $('#wizardContent').innerHTML = `<fieldset class="field"><legend>INPUT SOURCE</legend><div class="choice-grid"><label class="choice"><input id="sourceStory" type="radio" name="inputSource" value="STORY_CONTENT" ${wizard.source === 'STORY_CONTENT' ? 'checked' : ''}><strong>STORY / CONTENT</strong><small>Supply content.md or narration text. Run the full pipeline.</small></label><label class="choice"><input type="radio" name="inputSource" value="EXISTING_AUDIO" ${wizard.source === 'EXISTING_AUDIO' ? 'checked' : ''}><strong>EXISTING AUDIO</strong><small>Import narration audio. TTS will be skipped.</small></label><label class="choice"><input type="radio" name="inputSource" value="AUDIO_SRT" ${wizard.source === 'AUDIO_SRT' ? 'checked' : ''}><strong>AUDIO + SRT</strong><small>Import matching audio and SRT. TTS is skipped; SRT is timing.</small></label></div></fieldset><div style="margin-top:20px">${fields}${sourceStatusMarkup(wizard)}</div>`;
    document.querySelectorAll('input[name="inputSource"]').forEach(input => input.addEventListener('change', event => { wizard.source=event.target.value; wizard.execution=sourceExecution(wizard.source); wizard.sourceValidation=null; touchDraft(wizard,'source'); renderWizard(); focusWizardStep(); }));
    $('#contentInput')?.addEventListener('input', event => { wizard.content = event.target.value; touchDraft(wizard,'content'); });
    $('#contentFile')?.addEventListener('change', async event => { const file=event.target.files?.[0]; if (file) { const content=await file.text(); if (activeDraft(wizard)) { wizard.content=content; touchDraft(wizard,'content'); $('#contentInput').value=wizard.content; } } });
    $('#existingAudio')?.addEventListener('change', event => readBrowserImport(event,'importedAudio'));
    $('#existingSrt')?.addEventListener('change', event => readBrowserImport(event,'importedSrt'));
  } else if (wizard.step === 2) {
    const contextualStyle = wizard.mode === 'ambient_story'
      ? `<fieldset class="field contextual-field" id="ambientStyleField"><legend>Style</legend><div class="choice-grid"><label class="choice"><input type="radio" name="ambientStyle" value="quiet_verdict" ${wizard.ambientStyle === 'quiet_verdict' ? 'checked' : ''}><strong>Quiet Verdict</strong><small>Cool-neutral institutional tension with restrained, mostly static presentation.</small></label><label class="choice"><input type="radio" name="ambientStyle" value="hidden_mastery" ${wizard.ambientStyle === 'hidden_mastery' ? 'checked' : ''}><strong>Hidden Mastery</strong><small>Warm tactile realism for underestimated skill and meaningful recurring objects.</small></label></div></fieldset>`
      : wizard.mode === 'full_image'
        ? `<fieldset class="field contextual-field" id="fullImageSettings"><legend>FULL IMAGE</legend><fieldset class="field"><legend>Scene / Image duration</legend><div class="choice-grid">${[10,15,20,30,60].map(seconds => `<label class="choice"><input type="radio" name="fullImagePreset" value="${seconds}" ${Number(wizard.fullImage.image_duration_seconds) === seconds ? 'checked' : ''}><strong>${seconds} sec</strong></label>`).join('')}<label class="choice"><input type="radio" name="fullImagePreset" value="custom" ${[10,15,20,30,60].includes(Number(wizard.fullImage.image_duration_seconds)) ? '' : 'checked'}><strong>Custom</strong></label></div><div class="field" style="margin-top:12px" ${[10,15,20,30,60].includes(Number(wizard.fullImage.image_duration_seconds)) ? 'hidden' : ''}><label for="fullImageDuration">Custom seconds</label><input id="fullImageDuration" type="number" min="5" max="120" step="1" value="${esc(wizard.fullImage.image_duration_seconds)}"></div></fieldset><div class="settings-grid"><div class="field"><label for="fullImageCadence">Cadence</label><select id="fullImageCadence"><option value="SEMANTIC_ADAPTIVE" ${wizard.fullImage.cadence === 'SEMANTIC_ADAPTIVE' ? 'selected' : ''}>Semantic Adaptive</option><option value="FIXED" ${wizard.fullImage.cadence === 'FIXED' ? 'selected' : ''}>Fixed</option></select></div></div><div class="choice-grid"><label class="choice"><strong>Motion</strong><small>AUTO CONTINUOUS ZOOM</small></label><label class="choice"><input id="fullImageWaveform" type="checkbox" ${wizard.fullImage.audio_visualizer ? 'checked' : ''}><strong>Waveform: ${wizard.fullImage.audio_visualizer ? 'ON' : 'OFF'}</strong><small>Uses the final narration audio.</small></label></div></fieldset>`
        : `<fieldset class="field contextual-field"><legend>Visual tone</legend><div class="choice-grid"><label class="choice"><input type="radio" name="style" value="natural" ${wizard.style === 'natural' ? 'checked' : ''}><strong>Natural cinematic</strong><small>Restrained, story-first visuals with dependable defaults.</small></label><label class="choice"><input type="radio" name="style" value="documentary" ${wizard.style === 'documentary' ? 'checked' : ''}><strong>Quiet documentary</strong><small>Grounded pacing and observational visual language.</small></label></div></fieldset>`;
    const narratorHelp = installedVoices().length ? (wizard.voice ? 'Kokoro Local uses the installed narrator you select here.' : 'The saved default narrator is unavailable. Choose an installed narrator before continuing.') : 'No installed Kokoro narrators are available. Configure Kokoro in Settings before creating a video.';
    const sourceContext = wizard.source === 'STORY_CONTENT' ? `<div class="field" style="margin-top:20px"><label for="voiceChoice">Narrator voice</label><select id="voiceChoice" ${installedVoices().length ? '' : 'disabled'}>${voiceOptions(wizard.voice)}</select><small>${esc(narratorHelp)}</small></div>` : `<section class="surface" style="margin-top:20px"><strong>${esc(sourceLabel(wizard.source))}</strong><p class="hint">Narration audio: IMPORT · TTS: SKIP · Timing: ${wizard.source === 'AUDIO_SRT' ? 'SRT' : 'ALIGNMENT'}.</p></section>`;
    $('#wizardContent').innerHTML = `<fieldset class="field"><legend>Format</legend><div class="choice-grid format-grid"><label class="choice"><input id="formatChoice" type="radio" name="format" value="hybrid_hook" ${wizard.mode === 'hybrid_hook' ? 'checked' : ''}><strong>Cinematic opening</strong><small>Video-led opening with an image-led story body.</small></label><label class="choice"><input type="radio" name="format" value="full_video_ai" ${wizard.mode === 'full_video_ai' ? 'checked' : ''}><strong>Full video animation</strong><small>Generated video coverage for every final scene.</small></label><label class="choice"><input type="radio" name="format" value="ambient_story" ${wizard.mode === 'ambient_story' ? 'checked' : ''}><strong>Ambient Story</strong><small>Narrative-led long-form video with a few chapter images and subtle local motion.</small></label><label class="choice"><input type="radio" name="format" value="full_image" ${wizard.mode === 'full_image' ? 'checked' : ''}><strong>FULL IMAGE</strong><small>Images only, AUTO CONTINUOUS ZOOM, and optional waveform.</small></label></div></fieldset>${contextualStyle}${sourceContext}`;
    document.querySelectorAll('input[name="format"]').forEach(input => input.addEventListener('change', event => { wizard.mode = event.target.value; touchDraft(wizard,'mode'); renderWizard(); document.querySelector(`input[name="format"][value="${wizard.mode}"]`)?.focus(); }));
    document.querySelectorAll('input[name="style"]').forEach(input => input.addEventListener('change', event => { wizard.style = event.target.value; touchDraft(wizard,'style'); }));
    document.querySelectorAll('input[name="ambientStyle"]').forEach(input => input.addEventListener('change', event => { wizard.ambientStyle = event.target.value; touchDraft(wizard,'ambientStyle'); }));
    $('#fullImageDuration')?.addEventListener('input', event => { wizard.fullImage.image_duration_seconds = Number(event.target.value); touchDraft(wizard,'fullImage'); });
    document.querySelectorAll('input[name="fullImagePreset"]').forEach(input => input.addEventListener('change', event => { if (event.target.value !== 'custom') wizard.fullImage.image_duration_seconds=Number(event.target.value); else if ([10,15,20,30,60].includes(Number(wizard.fullImage.image_duration_seconds))) wizard.fullImage.image_duration_seconds=25; touchDraft(wizard,'fullImage'); renderWizard(); }));
    $('#fullImageCadence')?.addEventListener('change', event => { wizard.fullImage.cadence = event.target.value; touchDraft(wizard,'fullImage'); });
    $('#fullImageWaveform')?.addEventListener('change', event => { wizard.fullImage.audio_visualizer = event.target.checked; touchDraft(wizard,'fullImage'); renderWizard(); });
    $('#voiceChoice')?.addEventListener('change', event => { wizard.voice = event.target.value; touchDraft(wizard,'voice'); });
  } else {
    const source = wizard.source;
    const visualRun = wizard.mode === 'full_image' ? 'Image generation: RUN · Video generation: SKIP' : 'Visual generation: RUN';
    $('#wizardContent').innerHTML = `<p class="hint">Check these choices before Story Auto creates the project.</p><dl class="review-summary"><div class="summary-row"><dt>Input source</dt><dd>${esc(sourceLabel(source))}</dd><button class="change-step" data-change-step="1" type="button">Change</button></div><div class="summary-row"><dt>Narration</dt><dd>${source === 'STORY_CONTENT' ? esc(wizard.info?.title || voiceName(wizard.voice)) : esc(wizard.importedAudio?.filename || 'Not selected')}</dd><button class="change-step" data-change-step="1" type="button">Change</button></div><div class="summary-row"><dt>Format</dt><dd>${esc(humanMode(wizard.mode))}</dd><button class="change-step" data-change-step="2" type="button">Change</button></div>${wizard.mode === 'full_image' ? `<div class="summary-row"><dt>Scene duration</dt><dd>${esc(wizard.fullImage.image_duration_seconds)} seconds · ${esc(wizard.fullImage.cadence === 'FIXED' ? 'Fixed' : 'Semantic Adaptive')} · Waveform ${wizard.fullImage.audio_visualizer ? 'ON' : 'OFF'} · AUTO CONTINUOUS ZOOM</dd><button class="change-step" data-change-step="2" type="button">Change</button></div>` : ''}</dl><section class="surface" style="margin-top:22px"><h3>Execution summary</h3><p class="hint">Narration audio: ${source === 'STORY_CONTENT' ? 'GENERATE' : 'IMPORT'}<br>TTS: ${source === 'STORY_CONTENT' ? 'RUN' : 'SKIP'}<br>Timing: ${source === 'AUDIO_SRT' ? 'SRT' : source === 'STORY_CONTENT' ? 'RUN' : 'ALIGNMENT'}<br>Visual planning: RUN<br>${visualRun}<br>QC: RUN<br>Compose: RUN</p></section>`;
    document.querySelectorAll('[data-change-step]').forEach(button => button.addEventListener('click', () => { wizard.step = Number(button.dataset.changeStep); touchDraft(wizard,'step'); renderWizard(); focusWizardStep(); }));
  }
  $('#wizardActions').innerHTML = `<button class="button-quiet" id="cancelWizard" type="button">Cancel</button><div class="right">${wizard.step > 1 ? '<button id="wizardBack" type="button">Back</button>' : ''}<button class="button-primary" id="wizardNext" type="button">${wizard.step === 3 ? 'Create video' : 'Continue'}</button></div>`;
  $('#cancelWizard').addEventListener('click', closeWizard);
  $('#wizardBack')?.addEventListener('click', () => { wizard.step -= 1; touchDraft(wizard,'step'); renderWizard(); focusWizardStep(); });
  $('#wizardNext').addEventListener('click', advanceWizard);
}

async function advanceWizard() {
  const wizard = state.wizard;
  if (!wizard) return;
  if (wizard.step === 1) {
    wizard.content = $('#contentInput')?.value || wizard.content;
    const binding=draftBinding(wizard);
    if (wizard.source === 'STORY_CONTENT' || wizard.source === 'EXISTING_AUDIO') {
      try {
        const info=await api('/api/validate-content',{method:'POST',body:JSON.stringify({content:wizard.content})});
        if (!bindingIsCurrent(wizard,binding)) return;
        wizard.info=info;
      }
      catch (_) { if (!bindingIsCurrent(wizard,binding)) return; showWizardError(wizard.source === 'EXISTING_AUDIO' ? 'Add the canonical narration text needed to plan visuals.' : 'Add exactly one non-empty Narration section before continuing.','contentInput'); $('#contentInput')?.focus(); return; }
    }
    if (!bindingIsCurrent(wizard,binding)) return;
    if (wizard.source !== 'STORY_CONTENT') {
      if (!wizard.importedAudio?.base64) { showWizardError('No narration audio has been selected.','existingAudio'); return; }
      if (wizard.source === 'AUDIO_SRT' && !wizard.importedSrt?.base64) { showWizardError('A matching SRT file is required.','existingSrt'); return; }
      try { await validateSourceImports(wizard); } catch (error) { if (!activeDraft(wizard)) return; showWizardError(friendlyError(error).message,wizard.source === 'AUDIO_SRT' ? 'existingSrt' : 'existingAudio'); return; }
    }
    if (!bindingIsCurrent(wizard,binding)) return;
    wizard.execution=sourceExecution(wizard.source); wizard.step = 2; touchDraft(wizard,'step'); renderWizard(); focusWizardStep();
    return;
  }
  if (wizard.step === 2) {
    if (!['hybrid_hook','full_video_ai','ambient_story','full_image'].includes(wizard.mode)) { showWizardError('Choose a production format.','formatChoice'); return; }
    if (wizard.mode === 'ambient_story' && !['quiet_verdict','hidden_mastery'].includes(wizard.ambientStyle)) { showWizardError('Choose an Ambient Story style.','ambientStyleField'); return; }
    if (wizard.mode === 'full_image' && (!Number.isFinite(Number(wizard.fullImage.image_duration_seconds)) || Number(wizard.fullImage.image_duration_seconds) < 5 || Number(wizard.fullImage.image_duration_seconds) > 120 || !['SEMANTIC_ADAPTIVE','FIXED'].includes(wizard.fullImage.cadence))) { showWizardError('Choose an image duration between 5 and 120 seconds and a cadence.','fullImageSettings'); return; }
    if (wizard.source === 'STORY_CONTENT' && !hasInstalledVoice(wizard.voice)) { showWizardError('Choose an installed narrator before continuing.','voiceChoice'); return; }
    wizard.step = 3; touchDraft(wizard,'step'); renderWizard(); focusWizardStep(); return;
  }
  if (wizard.creating) return;
  const button = $('#wizardNext'); wizard.creating = true; button.disabled = true; button.textContent = 'Creating…';
  try {
    const settings = clone(state.creationDefaults?.creation_defaults || state.settings?.creation_defaults || {});
    const existingKokoro = settings.tts?.kokoro_local || {};
    wizard.execution=sourceExecution(wizard.source);
    if (wizard.execution === 'FULL') settings.tts = {provider:'kokoro_local',allow_cross_provider_fallback:false,kokoro_local:{...existingKokoro,voice_id:wizard.voice}};
    else delete settings.tts;
    settings.ui = {...settings.ui,production_style:wizard.style,input_source:wizard.source};
    settings.execution = {mode:wizard.execution};
    if (wizard.mode === 'ambient_story') settings.ambient_style = wizard.ambientStyle; else delete settings.ambient_style;
    if (wizard.mode === 'full_image') settings.full_image = {...wizard.fullImage, image_duration_seconds:Number(wizard.fullImage.image_duration_seconds), motion:'AUTO_CONTINUOUS_ZOOM'}; else delete settings.full_image;
    const created = await api('/api/projects',{method:'POST',body:JSON.stringify({render_mode:wizard.mode,ambient_style:wizard.mode === 'ambient_story' ? wizard.ambientStyle : null,content:wizard.source === 'AUDIO_SRT' ? null : wizard.content,settings,imported_audio:wizard.execution === 'FULL' ? null : wizard.importedAudio,imported_srt:wizard.source === 'AUDIO_SRT' ? wizard.importedSrt : null})});
    state.projects = [created,...state.projects.filter(project => project.project_id !== created.project_id)];
    state.project = created.project_id; state.snapshot = created; state.view = 'project'; setNav('home'); renderProject(); focusMain();
    closeWizard(); toast('Video project created.');
  } catch (error) { wizard.creating = false; showWizardError(friendlyError(error).message); button.disabled = false; button.textContent = 'Create video'; }
}

function closeWizard() {
  const draft=state.wizard;
  if (draft) { draft.revision += 1; state.wizard=null; }
  const dialog = $('#newVideoDialog'); if (dialog.open) dialog.close();
}

$('#closeWizard').addEventListener('click', closeWizard);
$('#newVideoDialog').addEventListener('cancel', event => { event.preventDefault(); closeWizard(); });
$('#homeNav').addEventListener('click', () => showHome(true));
$('#settingsNav').addEventListener('click', async () => { if (!state.projects.length) { try { await loadProjects(); } catch (_) {} } await showSettings(); });

window.addEventListener('unhandledrejection', event => { event.preventDefault(); toast(friendlyError(event.reason).message,true); });
showHome().catch(error => { $('#view').innerHTML = errorCard(friendlyError(error)); bindErrorActions(); });
