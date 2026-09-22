const state = {
  view: 'home', projects: [], project: null, snapshot: null, settings: null,
  busy: false, busyLabel: '', error: null, actionOutcome: null, lastAction: null, runToken: null,
  wizard: null, creationDefaults: null, nextDraftId: 0, projectOpenToken: null
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

function backendProductionWorking(production) {
  const terminalOrIdle = ['RECOVERY_READY','NEEDS_ATTENTION','BLOCKED','COMPLETE'];
  return !terminalOrIdle.includes(production?.pipeline_status) && ['RUNNING','RECOVERING'].includes(production?.pipeline_status);
}

function visibleProductionWorking() {
  const production = state.snapshot?.production;
  // A one-click run begins from a saved READY snapshot.  Until the polling
  // response replaces that snapshot, the in-flight action is positive live
  // ownership and must keep the workspace visibly Working.
  if (['RECOVERY_READY','NEEDS_ATTENTION','BLOCKED','COMPLETE'].includes(production?.pipeline_status)) return false;
  return state.busy || backendProductionWorking(production);
}

function syncActivityPresentation() {
  const working = visibleProductionWorking();
  $('#view').setAttribute('aria-busy', String(working));
  document.querySelector('.loading-line')?.remove();
  document.querySelector('#busyReason')?.remove();
  if (working) document.body.insertAdjacentHTML('beforeend', '<div class="loading-line" aria-hidden="true"></div>');
  if (working && state.busyLabel) document.body.insertAdjacentHTML('beforeend', `<span id="busyReason" class="sr-only" role="status">${esc(state.busyLabel)}</span>`);
  $('#runtimeState').textContent = working ? 'Working' : 'Ready';
}

function setBusy(value, label = '') {
  state.busy = value;
  state.busyLabel = label;
  syncActivityPresentation();
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

function humanMode(mode) { return mode === 'full_video_ai' ? 'Full Video' : mode === 'ambient_story' ? 'Ambient Story (deferred)' : mode === 'full_image' ? 'Full Image' : 'Hybrid Visual'; }
function humanAmbientStyle(style) { return style === 'hidden_mastery' ? 'Hidden Mastery' : 'Quiet Verdict'; }
function chipClass(project) { return project.attention?.length ? 'attention' : project.user_status === 'Complete' ? 'success' : ''; }

async function loadProjects() {
  const value = await api('/api/projects');
  state.projects = value.projects || [];
  return state.projects;
}

function projectCard(project) {
  const action = project.primary_action || {action:'Open project', action_id:'open'};
  const primary = `<button class="button-primary" type="button" data-project-action="${esc(action.action_id)}" data-project="${esc(project.project_id)}">${esc(action.action)}</button>`;
  return `<article class="project-card ${project.attention?.length ? 'is-attention' : ''}">
    <div class="card-top"><div><h3>${esc(project.title)}</h3><p class="meta">${esc(formatUpdated(project.updated_at))} · ${esc(humanMode(project.render_mode))}${project.ambient_style_label ? ` · ${esc(project.ambient_style_label)}` : ''}</p></div><span class="status-chip ${chipClass(project)}">${esc(project.user_status)}</span></div>
    <div class="card-progress"><small>${esc(project.current_activity)}</small><strong>${Number(project.progress || 0)}%</strong><div class="progress-track" role="progressbar" aria-label="${esc(project.title)} progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(project.progress || 0)}"><span style="width:${Number(project.progress || 0)}%"></span></div></div>
    <div class="card-actions"><button class="text-button" type="button" data-open-project="${esc(project.project_id)}">View project</button>${primary}</div>
  </article>`;
}

function bindProjectCards() {
  document.querySelectorAll('[data-open-project]').forEach(button => button.addEventListener('click', () => openProject(button.dataset.openProject)));
  document.querySelectorAll('[data-project-action]').forEach(button => button.addEventListener('click', async () => {
    const projectId = button.dataset.project;
    const intendedAction = button.dataset.projectAction;
    const opened = await openProject(projectId, false);
    if (!opened) return;
    if (state.project !== projectId || !state.snapshot?.production) return;
    const freshAction = state.snapshot.production.next_action?.action || 'review_project';
    if (freshAction !== intendedAction) {
      toast('This project has changed. Review its current state before continuing.');
      focusMain();
      return;
    }
    // The refreshed completed workspace contains the validated final preview
    // and its link. Never open an asset from the compact Home card snapshot.
    if (freshAction === 'open_final') { focusMain(); return; }
    await handleProjectAction(freshAction);
  }));
}

async function showHome(announce = false) {
  state.view = 'home'; state.project = null; state.snapshot = null; state.error = null; state.actionOutcome = null;
  setNav('home');
  setHeader('YOUR VIDEOS','Home','<button class="button-primary" id="newVideoTop" type="button">+ New video</button>');
  $('#newVideoTop').addEventListener('click', openWizard);
  const view = $('#view');
  view.innerHTML = '<div class="empty-library"><p>Loading your videos…</p></div>';
  try { await loadProjects(); } catch (error) {
    view.innerHTML = errorCard(friendlyError(error)); bindErrorActions(); return;
  }
  const attention = state.projects.filter(project => project.attention?.length);
  const recent = state.projects.filter(project => !project.attention?.length);
  view.innerHTML = `<section class="hero">
    <div><p class="eyebrow">CONTENT TO FINISHED VIDEO</p><h2>Turn your story or narration into a finished video.</h2><p>Start with story text, existing narration audio, or matching audio and SRT. Story Auto guides production from source to final review.</p><button class="button-primary" id="newVideoHero" type="button">+ New video</button></div>
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
  const token = Symbol(projectId); state.projectOpenToken = token;
  const ownsView = () => state.projectOpenToken === token && state.view === 'project' && state.project === projectId && !$('#newVideoDialog').open;
  state.view = 'project'; state.project = projectId; state.snapshot = null; state.error = null; state.actionOutcome = null;
  setNav('home'); setBusy(true,'Opening project');
  try {
    const snapshot = await api(`/api/projects/${encodeURIComponent(projectId)}/workspace`);
    if (!ownsView()) return false;
    state.snapshot = snapshot; setBusy(false); renderProject();
  }
  catch (error) {
    if (ownsView()) { setHeader('PROJECT','Could not open project'); $('#view').innerHTML = errorCard(friendlyError(error)); bindErrorActions(); }
    return false;
  }
  finally { if (state.projectOpenToken === token && state.busy && !state.runToken) setBusy(false); }
  if (moveFocus) focusMain();
  return true;
}

function stageMarkup(workspace) {
  const names = [['SOURCE','Source'],['TIMING','Timing'],['PLAN','Plan'],['VISUALS','Visuals'],['QUALITY','Quality'],['RENDER','Final video']];
  const stages=workspace.production.stages, active=workspace.production.active_stage;
  return `<ol class="stage-list" aria-label="Production stages">${names.map(([id,label]) => { const stage=stages[id] || {}; const state=stage.status === 'COMPLETE' ? 'is-done' : id === active ? 'is-current' : stage.status === 'BLOCKED' ? 'is-blocked' : ''; const count=id === 'VISUALS' && stage.total_items ? `<small>${stage.completed_items} / ${stage.total_items}</small>` : ''; return `<li class="${state}" ${id === active ? 'aria-current="step"' : ''}>${esc(label)}${count}</li>`; }).join('')}</ol>`;
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

function fullVideoProviderSurface(snapshot) {
  const provider = snapshot.full_video_provider;
  if (!provider) return '';
  const budget = provider.budget || {};
  const budgetParts = [];
  if (budget.balance !== null && budget.balance !== undefined) budgetParts.push(`Balance ${esc(budget.balance)} credits`);
  if (budget.estimate_credits !== null && budget.estimate_credits !== undefined) budgetParts.push(`Quote ${esc(budget.estimate_credits)} credits`);
  if (budget.max_credits !== null && budget.max_credits !== undefined) budgetParts.push(`Bound ${esc(budget.max_credits)} credits`);
  if (budget.unlock_credits !== null && budget.unlock_credits !== undefined) budgetParts.push(`Keep/unlock ${esc(budget.unlock_credits)} credits`);
  const routing = provider.routing_enabled ? 'Production enabled' : 'Integration staged — production routing remains locked until Goal 54 UAT is accepted.';
  const preview = provider.preview_path ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,provider.preview_path)}" aria-label="Exact locked Elyum preview"></video>` : '';
  let controls = '';
  if (provider.action === 'REVIEW_PREVIEW') {
    controls = `<div class="field"><label>Review reason<input data-elyum-review-reason type="text" autocomplete="off" placeholder="Why this exact preview is acceptable or should be rejected"></label><small>This reason is bound to the exact preview SHA-256.</small></div><div class="button-row"><button class="button-primary" data-elyum-review="ACCEPT" data-request-id="${esc(provider.request_id)}" type="button">Accept exact preview</button><button data-elyum-review="REJECT" data-request-id="${esc(provider.request_id)}" type="button">Reject exact preview</button></div>`;
  } else if (provider.action === 'KEEP_PREVIEW') {
    const cost = budget.unlock_credits !== null && budget.unlock_credits !== undefined ? ` (${esc(budget.unlock_credits)} credits)` : '';
    controls = `<div class="button-row"><button class="button-primary" data-elyum-keep data-request-id="${esc(provider.request_id)}" type="button">Keep / unlock${cost}</button></div>`;
  } else if (provider.action === 'KILL_PREVIEW') {
    controls = `<div class="button-row"><button data-elyum-kill data-request-id="${esc(provider.request_id)}" type="button">Kill rejected preview</button></div>`;
  } else if (provider.action === 'REACQUIRE_KEPT_OUTPUT') {
    controls = `<div class="button-row"><button class="button-primary" data-elyum-reacquire data-request-id="${esc(provider.request_id)}" type="button">Retry clean output download</button></div>`;
  } else if (provider.action === 'AUTHORIZE_REPLACEMENT') {
    controls = `<div class="field"><label>Replacement reason<input data-elyum-replacement-reason type="text" autocomplete="off" placeholder="Why one new generation is required"></label><small>The killed attempt stays immutable. This authorizes exactly one new logical attempt.</small></div><div class="field"><label>Revised provider prompt<textarea data-elyum-replacement-prompt rows="10" spellcheck="false">${esc(provider.request_prompt || '')}</textarea></label><small>Edit the full prompt for the replacement attempt. Story Auto snapshots this exact text and SHA-256 into the new attempt before provider dispatch.</small></div><div class="button-row"><button class="button-primary" data-elyum-replace data-request-id="${esc(provider.request_id)}" type="button">Authorize one replacement</button></div>`;
  }
  const exact = provider.preview_sha256 ? `<details class="disclosure"><summary>Exact acceptance surface</summary><div class="technical">Preview SHA-256: ${esc(provider.preview_sha256)}${provider.selected_sha256 ? `\nSelected SHA-256: ${esc(provider.selected_sha256)}` : ''}</div></details>` : '';
  return `<section class="surface"><div class="surface-head"><div><p class="eyebrow">FULL VIDEO PROVIDER</p><h2>${esc(provider.provider_label)}</h2><p>${esc(routing)}</p></div><span class="status-chip ${provider.owner_decision_required ? 'attention' : provider.status === 'SUCCEEDED' ? 'success' : ''}">${esc(provider.status)}</span></div><div class="choice-grid"><div class="choice"><strong>Continuation safety</strong><small>${esc(provider.continuation_behavior)}</small></div><div class="choice"><strong>Provider state</strong><small>${provider.known_job ? 'A durable provider job is already known. Continue must resume it.' : 'No durable provider job is currently bound to this request.'}</small></div>${budgetParts.length ? `<div class="choice"><strong>Budget / preflight</strong><small>${budgetParts.map(esc).join(' · ')}</small></div>` : ''}</div>${preview}${controls}${provider.action === 'RECONCILE_CONSEQUENCE' ? '<div class="attention-card"><div><strong>Consequence reconciliation required</strong><p>Story Auto will not repeat Keep or Kill automatically because the provider outcome is ambiguous.</p></div></div>' : ''}${exact}</section>`;
}

function openingBuilderSurface(snapshot) {
  const opening = snapshot.opening_builder;
  if (!opening) return '';
  if (opening.status === 'NOT_CONFIGURED') {
    return `<section class="surface"><div class="surface-head"><div><p class="eyebrow">HYBRID VISUAL</p><h2>Opening Builder</h2><p>The manual opening contract has not been prepared for this project yet. If canonical opening video requests already exist, Story Auto can convert their exact prompts into manual slots without calling a provider.</p></div><span class="status-chip">NOT CONFIGURED</span></div><div class="button-row"><button data-opening-prepare type="button">Prepare opening prompts</button></div><small>This action only materializes the local prompt/slot contract.</small></section>`;
  }
  const target = opening.render_target || {};
  const providers = snapshot.opening_api_providers || {byteplus:snapshot.opening_api_provider || {},elyum:{}};
  const byteplus = providers.byteplus || {};
  const elyum = providers.elyum || {};
  const dola = providers.dola || {};
  const flowCookie = providers.flow_cookie || {};
  const providerPolicy = String(snapshot.opening_provider_policy || 'AUTO').toUpperCase();
  const allowBytePlus = providerPolicy === 'AUTO' || providerPolicy === 'BYTEPLUS';
  const allowElyum = providerPolicy === 'AUTO' || providerPolicy === 'ELYUM';
  const allowDola = providerPolicy === 'AUTO' || providerPolicy === 'DOLA';
  const slots = (opening.slots || []).map(slot => {
    const ready = slot.status === 'READY' && slot.asset_ready;
    const api = slot.api_generation || {};
    const providerId = api.provider || '';
    const apiState = api.status || 'NOT_STARTED';
    const noProvider = !providerId;
    const byteplusActive = providerId === 'byteplus_seedance';
    const elyumActive = providerId === 'elyum_seedance';
    const dolaActive = providerId === 'dola_cookie';
    const flowCookieActive = providerId === 'flow_cookie';
    const preflight = slot.elyum_preflight || {};
    const elyumModels = Array.isArray(preflight.models) ? preflight.models : [];
    const affordableModels = elyumModels.filter(item => item.affordable === true);
    let providerControls = '';
    let flowControls = '';
    if (!ready && noProvider && providerPolicy === 'AUTO') {
      let inner = '<small>Save a named Flow session in Settings first. Existing image and body generation are unchanged.</small>';
      if (flowCookie.configured) {
        if (Number(slot.duration_seconds) > 8) inner = '<small>Flow reference video supports opening slots up to 8 seconds. Import a clip for this longer slot.</small>';
        else if (!flowCookie.generation_enabled) inner = '<small>Experimental Flow generation is not enabled for this runtime. Saved sessions can still be tested in Settings.</small>';
        else inner = `<label>Flow session <select data-opening-flow-account="${esc(slot.slot_id)}" aria-label="Flow session for ${esc(slot.slot_id)}">${(flowCookie.accounts || []).map(a=>`<option value="${esc(a.account_id)}">${esc(a.account_id)} · revision ${esc(a.revision)}</option>`).join('')}</select></label><label>Flow project URL <input type="url" data-opening-flow-project="${esc(slot.slot_id)}" aria-label="Flow project for ${esc(slot.slot_id)}" placeholder="https://flow.google.com/project/..."></label><label>Reference PNG <input type="file" accept="image/png,.png" data-opening-flow-reference="${esc(slot.slot_id)}" aria-label="Flow reference for ${esc(slot.slot_id)}"></label><small>One 8-second video, trimmed to this slot. Your existing Flow allowance may be consumed.</small><button data-opening-flow="${esc(slot.slot_id)}" type="button">Generate one Flow video</button>`;
      }
      flowControls = `<details class="opening-flow-options"><summary>Flow video from reference image (experimental)</summary>${inner}</details>`;
    } else if (!ready && flowCookieActive) {
      flowControls = `<small>Flow session ${esc(api.account_id)} · revision ${esc(api.revision)}. Recovery checks this same video only; it never creates a replacement.</small><button data-opening-flow="${esc(slot.slot_id)}" data-resume="true" type="button">Check / recover Flow video</button><button data-opening-flow-reset="${esc(slot.slot_id)}" type="button">Reset unused setup</button><small>Reset is allowed only when saved evidence proves that no upload or generation was attempted. Attempt history is preserved.</small>`;
    }
    if (!ready && noProvider) {
      if (allowDola && dola.configured && Number(slot.duration_seconds) <= 10) {
        providerControls += `<label>Dola account <select aria-label="Dola account for ${esc(slot.slot_id)}" data-opening-dola-account="${esc(slot.slot_id)}">${(dola.accounts || []).map(a => `<option value="${esc(a.account_id)}">${esc(a.account_id)}</option>`).join('')}</select></label><button data-opening-dola="${esc(slot.slot_id)}" type="button">Generate with Dola</button>`;
      }
      if (allowBytePlus && byteplus.status === 'READY') providerControls += `<button data-opening-api="${esc(slot.slot_id)}" type="button">Generate with BytePlus</button>`;
      if (allowElyum && elyum.configured) {
        if (preflight.status === 'READY' && elyumModels.length) {
          const options = elyumModels.map(item => `<option value="${esc(item.model_id)}" ${item.affordable ? '' : 'disabled'}>${esc(item.model_id)} · ${esc(item.estimate_credits)} credits${item.affordable ? '' : ' · insufficient balance'}</option>`).join('');
          providerControls += `<select data-opening-elyum-model="${esc(slot.slot_id)}">${options}</select>`;
          providerControls += affordableModels.length ? `<button data-opening-elyum-generate="${esc(slot.slot_id)}" type="button">Generate Elyum preview</button>` : '';
        } else {
          providerControls += `<button data-opening-elyum-preflight="${esc(slot.slot_id)}" type="button">Check Elyum options</button>`;
        }
      }
    } else if (!ready && dolaActive && apiState === 'FAILED_PRE_DISPATCH' && api.dispatch_state === 'NOT_DISPATCHED') {
      providerControls += `<button data-opening-dola="${esc(slot.slot_id)}" data-account="${esc(api.account_id)}" type="button">Try Dola after updating cookie</button>`;
    } else if (!ready && dolaActive && api.provider_task_id && !['SUCCEEDED','FAILED_TERMINAL'].includes(apiState)) {
      providerControls += `<button data-opening-dola="${esc(slot.slot_id)}" data-resume="true" type="button">Check / recover Dola video</button>`;
    } else if (!ready && byteplusActive && !['AMBIGUOUS','FAILED_TERMINAL'].includes(apiState)) {
      providerControls += `<button data-opening-api="${esc(slot.slot_id)}" type="button">Resume BytePlus generation</button>`;
    } else if (!ready && elyumActive) {
      const model = api.provider_model || '';
      if (['PRE_DISPATCH','SUBMITTED','GENERATING','WAIT_UNAVAILABLE','AMBIGUOUS','FAILED_PRE_DISPATCH','COST_BLOCKED','CREDIT_BLOCKED'].includes(apiState)) {
        providerControls += `<button data-opening-elyum-resume="${esc(slot.slot_id)}" data-model="${esc(model)}" type="button">${apiState === 'AMBIGUOUS' ? 'Reconcile same Elyum request' : 'Resume Elyum preview'}</button>`;
      } else if (apiState === 'PREVIEW_READY') {
        providerControls += `<button data-opening-elyum-accept="${esc(slot.slot_id)}" type="button">Accept preview</button><button class="button-quiet" data-opening-elyum-reject="${esc(slot.slot_id)}" type="button">Reject preview</button>`;
      } else if (apiState === 'KEEP_REQUIRED') {
        providerControls += `<button class="button-primary" data-opening-elyum-keep="${esc(slot.slot_id)}" data-credits="${esc(api.unlock_credits ?? '')}" type="button">Keep & use${api.unlock_credits != null ? ` · ${esc(api.unlock_credits)} credits` : ''}</button>`;
      } else if (apiState === 'KEEP_ACQUISITION_REQUIRED' && api.keep_confirmed) {
        providerControls += `<button class="button-primary" data-opening-elyum-acquire="${esc(slot.slot_id)}" type="button">Recover kept video</button>`;
      } else if (apiState === 'PREVIEW_REJECTED') {
        providerControls += `<button data-opening-elyum-kill="${esc(slot.slot_id)}" type="button">Kill & release hold</button>`;
      }
    }
    const unresolvedProvider = !!providerId && !['FAILED_PRE_DISPATCH','COST_BLOCKED','CREDIT_BLOCKED','FAILED_TERMINAL','KILLED','SUCCEEDED'].includes(apiState);
    const importButton = unresolvedProvider ? '' : `<label class="button">${ready ? 'Replace clip' : 'Import clip'}<input data-opening-import="${esc(slot.slot_id)}" type="file" accept="video/*" hidden></label>`;
    let apiNote = '';
    if (!ready && dolaActive) apiNote = `<small>Dola account: ${esc(api.account_id)}. ${api.provider_task_id ? 'Check again to recover the same video.' : 'Submission needs attention; a second video will not be submitted automatically.'} ${esc(api.failure_class || '')}</small>`;
    if (!ready && noProvider && allowDola && !dola.configured) apiNote = '<small>Add Dola accounts in Settings to use cookie-based text-to-video.</small>';
    if (!ready && noProvider && providerPolicy === 'MANUAL') apiNote = '<small>Opening provider policy is Manual only. Import a clip for this slot.</small>';
    else if (!ready && noProvider && providerPolicy === 'BYTEPLUS' && byteplus.status !== 'READY') apiNote = '<small>BytePlus is selected but not configured. Manual import remains available.</small>';
    else if (!ready && noProvider && providerPolicy === 'ELYUM' && !elyum.configured) apiNote = '<small>Elyum is selected but not configured. Manual import remains available.</small>';
    else if (!ready && noProvider && byteplus.status !== 'READY' && !elyum.configured && !dola.configured) apiNote = '<small>No video provider is configured. Add Dola accounts in Settings or import a clip.</small>';
    if (!ready && preflight.status === 'READY' && !affordableModels.length) apiNote = `<small>Elyum models are available, but the current balance (${esc(preflight.balance)}) is below every quoted option for this slot.</small>`;
    if (elyumActive && apiState === 'PREVIEW_READY') apiNote = '<small>Locked Elyum preview. It is not an Opening asset yet: review it, then Keep to spend and download the original.</small>';
    if (elyumActive && apiState === 'KEEP_REQUIRED') apiNote = '<small>Preview accepted. Keep is the Elyum spend boundary; Story Auto will not call it automatically.</small>';
    if (elyumActive && apiState === 'KEEP_ACQUISITION_REQUIRED') apiNote = '<small>Keep is confirmed. Recover the original video without another Keep charge.</small>';
    if (elyumActive && apiState === 'PREVIEW_REJECTED') apiNote = '<small>Preview rejected. Kill releases the held credits; manual import reopens after the consequence is resolved.</small>';
    if (elyumActive && ['KEEP_DISPATCHING','KILL_DISPATCHING','KEEP_AMBIGUOUS','KILL_AMBIGUOUS'].includes(apiState)) apiNote = '<small>Provider consequence outcome is unresolved. Story Auto will not retry automatically or switch providers.</small>';
    if (byteplusActive && apiState === 'AMBIGUOUS') apiNote = '<small>BytePlus submission is ambiguous. Story Auto will not submit or switch provider automatically.</small>';
    const lockedPreview = !ready && elyumActive && api.preview_asset?.path ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,api.preview_asset.path)}" aria-label="${esc(slot.slot_id)} Elyum locked preview"></video>` : '';
    const preview = ready && slot.normalized_asset?.path ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,slot.normalized_asset.path)}" aria-label="${esc(slot.slot_id)} normalized opening clip"></video>` : '';
    const sourceKind = slot.source_asset?.provider === 'flow_cookie' ? 'Generated by Flow' : slot.source_asset?.provider === 'dola_cookie' ? 'Generated by Dola' : slot.source_asset?.provider === 'elyum_seedance' ? 'Generated by Elyum' : slot.source_asset?.provider === 'byteplus_seedance' || (byteplusActive && apiState === 'SUCCEEDED') ? 'Generated by BytePlus' : 'Imported';
    const source = slot.source_asset ? `<small>${sourceKind} · ${esc(slot.source_asset.original_filename || 'clip')} · ${Number(slot.source_asset.duration_seconds || 0).toFixed(2)}s${slot.source_asset.had_audio ? ' · embedded audio stripped' : ''}</small>` : '<small>No clip bound yet.</small>';
    return `<article class="choice"><div class="surface-head"><div><strong>${esc(slot.slot_id)} · ${esc(slot.start)}-${esc(slot.end)}s</strong><small>${esc(slot.purpose)}</small></div><span class="status-chip ${ready ? 'success' : 'attention'}">${ready ? 'READY' : (apiState !== 'NOT_STARTED' ? esc(apiState) : 'MISSING')}</span></div><div class="technical opening-prompt">${esc(slot.prompt)}</div><div class="button-row"><button data-opening-copy="${esc(slot.slot_id)}" type="button">Copy prompt</button>${providerControls}${importButton}</div>${flowControls}${apiNote}${source}${lockedPreview}${preview}</article>`;
  }).join('');
  return `<section class="surface"><div class="surface-head"><div><p class="eyebrow">HYBRID VISUAL</p><h2>Opening Builder · ${esc(opening.opening_duration_seconds)}s</h2><p>Choose BytePlus, Elyum preview/Keep, or manual import per slot. Narration, subtitles, waveform, and final audio remain separate master tracks.</p></div><span class="status-chip ${opening.ready ? 'success' : 'attention'}">${opening.ready ? 'READY' : 'NEEDS CLIPS'}</span></div><div class="choice-grid"><div class="choice"><strong>Opening provider policy</strong><small>${esc(providerPolicy)}</small></div><div class="choice"><strong>Shared continuity</strong><small>${esc(opening.shared_context || '')}</small></div><div class="choice"><strong>Normalization target</strong><small>${esc(target.width || '?')}×${esc(target.height || '?')} · ${esc(target.fps || '?')} fps · silent MP4</small></div></div><div class="button-row"><button data-opening-copy-all type="button">Copy all opening prompts</button></div><div class="choice-grid opening-slot-grid">${slots}</div></section>`;
}

function hybridBodySurface(snapshot) {
  if (!snapshot.opening_builder || snapshot.opening_builder.status === 'NOT_CONFIGURED') return '';
  const body = snapshot.hybrid_body;
  if (!body) return `<section class="surface"><div class="surface-head"><div><p class="eyebrow">HYBRID BODY</p><h2>Images + semantic stock video</h2><p>Plan the body from the master narration clock. This is provider-free; Pexels is searched only when a stock slot is explicitly resolved later.</p></div><span class="status-chip">NOT PLANNED</span></div><div class="button-row"><button data-hybrid-body-plan type="button">Plan body recipe</button></div></section>`;
  const stock = (body.slots || []).filter(slot => slot.visual_type === 'STOCK_VIDEO');
  const images = (body.slots || []).filter(slot => slot.visual_type === 'IMAGE');
  const imageRows = images.map(slot => {
    const ready = !!slot.source_asset;
    return `<article class="choice"><div class="surface-head"><div><strong>${esc(slot.slot_id)} · ${esc(slot.start)}–${esc(slot.end)}s</strong><small>${esc(slot.effect || 'SLOW_PUSH')} · ${esc(slot.semantic_context || '')}</small></div><span class="status-chip ${ready ? 'success' : 'attention'}">${ready ? 'IMAGE READY' : 'IMAGE NEEDED'}</span></div><div class="button-row"><label class="button">${ready ? 'Replace image' : 'Import image'}<input data-hybrid-image-import="${esc(slot.slot_id)}" data-stock-fallback="false" type="file" accept="image/*" hidden></label></div></article>`;
  }).join('');
  const stockRows = stock.map(slot => {
    const attribution = slot.attribution || {};
    const credit = attribution.source_url ? `<a href="${esc(attribution.source_url)}" target="_blank" rel="noopener">${esc(attribution.text || 'Pexels source')}</a>` : 'Not selected yet';
    const pexelsReady = slot.status === 'READY' && !!slot.normalized_asset;
    const fallbackReady = !!slot.fallback_image_asset;
    const resolve = !pexelsReady ? `<button data-hybrid-stock-resolve="${esc(slot.slot_id)}" type="button">Find relevant Pexels clip</button>` : '';
    const fallback = `<label class="button">${fallbackReady ? 'Replace fallback image' : 'Import image fallback'}<input data-hybrid-image-import="${esc(slot.slot_id)}" data-stock-fallback="true" type="file" accept="image/*" hidden></label>`;
    const stateLabel = pexelsReady ? 'PEXELS READY' : fallbackReady ? 'IMAGE FALLBACK READY' : slot.status;
    return `<article class="choice"><div class="surface-head"><div><strong>${esc(slot.slot_id)} · ${esc(slot.start)}–${esc(slot.end)}s</strong><small>${esc(slot.provider_query || '')}</small></div><span class="status-chip ${pexelsReady || fallbackReady ? 'success' : 'attention'}">${esc(stateLabel)}</span></div><small>${credit}</small><div class="button-row">${resolve}${fallback}</div></article>`;
  }).join('');
  const preview = snapshot.hybrid_preview || {};
  const previewMissing = (preview.readiness?.missing || []).length;
  const previewVideo = preview.preview_ready && preview.preview_path ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,preview.preview_path)}" aria-label="Hybrid Visual mixed preview"></video>` : '';
  const previewAction = preview.readiness?.ready ? '<button class="button-primary" data-hybrid-preview-render type="button">Render mixed preview</button>' : `<small>${previewMissing} visual slot${previewMissing === 1 ? '' : 's'} still need an asset before mixed preview.</small>`;
  return `<section class="surface"><div class="surface-head"><div><p class="eyebrow">HYBRID BODY</p><h2>${images.length} image slots + ${stock.length} stock-video slots</h2><p>Timing follows narration. Imported visual audio is ignored; narration, subtitles and waveform remain continuous master tracks.</p></div><span class="status-chip">PLANNED</span></div><p><a href="https://www.pexels.com/" target="_blank" rel="noopener">Stock videos provided by Pexels</a></p><div class="choice-grid">${imageRows}${stockRows}</div><div class="surface-head"><div><h3>Mixed preview</h3><p>Opening → images/effects → stock/fallback → images, on the exact narration clock.</p></div><div class="button-row">${previewAction}</div></div>${previewVideo}</section>`;
}

function bindHybridBodyControls() {
  document.querySelectorAll('[data-hybrid-body-plan]').forEach(button => button.addEventListener('click', async () => {
    await runAction('plan_hybrid_body','Planning Hybrid Visual body from narration…');
  }));
  document.querySelectorAll('[data-hybrid-stock-resolve]').forEach(button => button.addEventListener('click', async () => {
    await runAction('resolve_hybrid_stock_slot','Finding and normalizing one relevant Pexels clip…',{slot_id:button.dataset.hybridStockResolve});
  }));
  document.querySelectorAll('[data-hybrid-image-import]').forEach(input => input.addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const imported_image = await openingFilePayload(file);
      await runAction('import_hybrid_body_image',`Binding ${input.dataset.hybridImageImport} image…`,{slot_id:input.dataset.hybridImageImport,imported_image,as_stock_fallback:input.dataset.stockFallback === 'true'});
    } catch (error) { toast(friendlyError(error).message,true); }
  }));
  document.querySelectorAll('[data-hybrid-preview-render]').forEach(button => button.addEventListener('click', async () => {
    await runAction('render_hybrid_preview','Rendering mixed Hybrid Visual preview with master audio/subtitles/waveform…');
  }));
}

async function openingFilePayload(file) {
  const encoded = await new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=() => resolve(String(reader.result).split(',')[1] || ''); reader.onerror=reject; reader.readAsDataURL(file); });
  return {filename:file.name,base64:encoded};
}

async function confirmFlowAction(message, actionLabel) {
  if (document.getElementById('flowConfirmDialog')) return false;
  const previousFocus=document.activeElement;
  const dialog=document.createElement('dialog');
  dialog.id='flowConfirmDialog';
  dialog.setAttribute('aria-labelledby','flowConfirmTitle');
  dialog.setAttribute('aria-describedby','flowConfirmMessage');
  dialog.innerHTML=`<div class="dialog-shell"><header class="dialog-head"><h2 id="flowConfirmTitle">Review Flow action</h2></header><div class="dialog-content"><p id="flowConfirmMessage">${esc(message)}</p></div><footer class="dialog-actions"><button type="button" data-flow-cancel autofocus>Cancel</button><button type="button" data-flow-confirm>${esc(actionLabel)}</button></footer></div>`;
  document.body.append(dialog);
  return new Promise(resolve=>{
    dialog.addEventListener('close',()=>{
      const approved=dialog.returnValue==='confirmed';
      dialog.remove();
      if(previousFocus?.isConnected) previousFocus.focus();
      resolve(approved);
    },{once:true});
    dialog.querySelector('[data-flow-cancel]').addEventListener('click',()=>dialog.close('cancelled'));
    dialog.querySelector('[data-flow-confirm]').addEventListener('click',()=>dialog.close('confirmed'));
    dialog.showModal();
  });
}

function bindOpeningBuilderControls() {
  document.querySelectorAll('[data-opening-flow-project]').forEach(input=>{
    input.value=state.snapshot?.opening_api_providers?.flow_cookie?.generation_project_url || '';
  });
  document.querySelectorAll('[data-opening-flow-reset]').forEach(button=>button.addEventListener('click',async()=>{
    if (!await confirmFlowAction('Reset this Flow setup only if saved evidence proves zero provider effects? History stays saved. This does not generate a replacement.','Reset unused setup')) return;
    await runAction('reset_unused_flow_cookie_opening','Checking whether setup can be reset safely...',{slot_id:button.dataset.openingFlowReset,confirm_reset:true});
  }));
  document.querySelectorAll('[data-opening-flow]').forEach(button=>button.addEventListener('click',async()=>{
    const slotId=button.dataset.openingFlow;
    if (button.dataset.resume) {
      await runAction('generate_flow_cookie_opening','Checking the same Flow video...',{slot_id:slotId,recovery_only:true});
      return;
    }
    const select = suffix=>document.querySelector(`[data-opening-flow-${suffix}="${CSS.escape(slotId)}"]`);
    const account=select('account')?.value || '';
    const project=select('project')?.value.trim() || '';
    const file=select('reference')?.files[0];
    if (!account || !project || !file) { toast('Choose a Flow session, project URL and reference PNG.',true); return; }
    if (file.size>20*1024*1024) { toast('Reference PNG must be 20 MB or smaller.',true); return; }
    if (!await confirmFlowAction(`Generate one 8-second Flow video for ${slotId}? Session: ${account}. Project: ${project}. Reference: ${file.name}. It will be trimmed to this slot and may consume your Flow allowance.`,'Generate one video')) return;
    button.disabled=true;
    try {
      const reference=await openingFilePayload(file);
      await runAction('generate_flow_cookie_opening','Creating one Flow reference video...',{slot_id:slotId,account_id:account,project_url:project,imported_reference:reference,confirm_generate:true});
    } catch (_) { toast('Could not read the reference PNG. Choose the file again.',true); }
    finally { button.disabled=false; }
  }));
  document.querySelectorAll('[data-opening-prepare]').forEach(button => button.addEventListener('click', async () => {
    await runAction('prepare_opening_builder','Preparing exact opening prompts from the saved plan…');
  }));
  document.querySelectorAll('[data-opening-copy-all]').forEach(button => button.addEventListener('click', async () => {
    const text = state.snapshot?.opening_builder?.copy_all_prompts || '';
    if (!text) return;
    try { await navigator.clipboard.writeText(text); toast('Opening prompt pack copied.'); }
    catch (_) { toast('Clipboard access is unavailable in this browser.',true); }
  }));
  document.querySelectorAll('[data-opening-copy]').forEach(button => button.addEventListener('click', async () => {
    const slot = (state.snapshot?.opening_builder?.slots || []).find(item => item.slot_id === button.dataset.openingCopy);
    if (!slot?.prompt) return;
    try { await navigator.clipboard.writeText(slot.prompt); toast(`${slot.slot_id} prompt copied.`); }
    catch (_) { toast('Clipboard access is unavailable in this browser.',true); }
  }));
  document.querySelectorAll('[data-opening-api]').forEach(button => button.addEventListener('click', async () => {
    await runAction('generate_opening_api',`Generating ${button.dataset.openingApi} with BytePlus API...`,{slot_id:button.dataset.openingApi});
  }));
  document.querySelectorAll('[data-opening-dola]').forEach(button => button.addEventListener('click', async () => {
    const slotId = button.dataset.openingDola;
    const account = document.querySelector(`[data-opening-dola-account="${CSS.escape(slotId)}"]`)?.value || button.dataset.account || '';
    if (!button.dataset.resume && !window.confirm(`Generate one Dola text-to-video clip for ${slotId} using account ${account}? A 5 or 10 second clip will be requested and trimmed to this slot. Account quota may be consumed. Image references are not supported yet.`)) return;
    await runAction('generate_dola_opening',button.dataset.resume ? 'Checking the same Dola video...' : 'Submitting one Dola video...',{slot_id:slotId,account_id:account});
  }));
  document.querySelectorAll('[data-opening-elyum-preflight]').forEach(button => button.addEventListener('click', async () => {
    await runAction('preflight_elyum_opening',`Checking Elyum models and cost for ${button.dataset.openingElyumPreflight}...`,{slot_id:button.dataset.openingElyumPreflight});
  }));
  document.querySelectorAll('[data-opening-elyum-generate]').forEach(button => button.addEventListener('click', async () => {
    const slotId=button.dataset.openingElyumGenerate;
    const selector=[...document.querySelectorAll('[data-opening-elyum-model]')].find(item => item.dataset.openingElyumModel === slotId);
    const modelId=selector?.value || '';
    if (!modelId) { toast('Choose an affordable Elyum model first.',true); return; }
    await runAction('generate_elyum_opening',`Generating locked Elyum preview for ${slotId}...`,{slot_id:slotId,model_id:modelId});
  }));
  document.querySelectorAll('[data-opening-elyum-resume]').forEach(button => button.addEventListener('click', async () => {
    await runAction('generate_elyum_opening',`Resuming exact Elyum request for ${button.dataset.openingElyumResume}...`,{slot_id:button.dataset.openingElyumResume,model_id:button.dataset.model || ''});
  }));
  document.querySelectorAll('[data-opening-elyum-accept]').forEach(button => button.addEventListener('click', async () => {
    await runAction('accept_elyum_opening',`Accepting locked preview for ${button.dataset.openingElyumAccept}...`,{slot_id:button.dataset.openingElyumAccept});
  }));
  document.querySelectorAll('[data-opening-elyum-reject]').forEach(button => button.addEventListener('click', async () => {
    await runAction('reject_elyum_opening',`Rejecting locked preview for ${button.dataset.openingElyumReject}...`,{slot_id:button.dataset.openingElyumReject});
  }));
  document.querySelectorAll('[data-opening-elyum-keep]').forEach(button => button.addEventListener('click', async () => {
    const credits=button.dataset.credits ? ` (${button.dataset.credits} credits)` : '';
    if (!window.confirm(`Keep this Elyum preview${credits} and use it in the Opening? This is the spend action.`)) return;
    await runAction('keep_elyum_opening',`Keeping and acquiring ${button.dataset.openingElyumKeep}...`,{slot_id:button.dataset.openingElyumKeep,confirm_spend:true});
  }));
  document.querySelectorAll('[data-opening-elyum-kill]').forEach(button => button.addEventListener('click', async () => {
    if (!window.confirm('Kill this Elyum preview and release its held credits? This may use the account kill allowance.')) return;
    await runAction('kill_elyum_opening',`Killing rejected preview for ${button.dataset.openingElyumKill}...`,{slot_id:button.dataset.openingElyumKill});
  }));
  document.querySelectorAll('[data-opening-elyum-acquire]').forEach(button => button.addEventListener('click', async () => {
    await runAction('keep_elyum_opening',`Recovering kept video for ${button.dataset.openingElyumAcquire}...`,{slot_id:button.dataset.openingElyumAcquire,confirm_spend:false});
  }));
  document.querySelectorAll('[data-opening-import]').forEach(input => input.addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const imported_video = await openingFilePayload(file);
      await runAction('import_opening_clip',`Normalizing ${input.dataset.openingImport}…`,{slot_id:input.dataset.openingImport,imported_video});
    } catch (error) { toast(friendlyError(error).message,true); }
  }));
}

function bindFullVideoProviderControls() {
  document.querySelectorAll('[data-elyum-review]').forEach(button => button.addEventListener('click', async () => {
    const decision = button.dataset.elyumReview;
    const input = button.closest('.surface')?.querySelector('[data-elyum-review-reason]');
    const reason = input?.value?.trim() || '';
    if (!reason) { toast('Add a reason for this exact preview decision.',true); input?.focus(); return; }
    await runAction('review_elyum_preview', decision === 'ACCEPT' ? 'Recording preview acceptance…' : 'Recording preview rejection…', {request_id:button.dataset.requestId,decision,reason});
  }));
  document.querySelectorAll('[data-elyum-keep]').forEach(button => button.addEventListener('click', async () => {
    const provider = state.snapshot?.full_video_provider || {};
    const credits = provider.budget?.unlock_credits;
    const suffix = credits !== null && credits !== undefined ? ` This may spend ${credits} provider credits.` : ' This may spend provider credits.';
    if (!window.confirm(`Keep and unlock this exact accepted preview?${suffix}`)) return;
    await runAction('keep_elyum_preview','Keeping and acquiring the clean output…',{request_id:button.dataset.requestId,confirm_spend:true});
  }));
  document.querySelectorAll('[data-elyum-kill]').forEach(button => button.addEventListener('click', async () => {
    const reason = state.snapshot?.full_video_provider?.preview_review?.reason || 'Owner rejected the exact locked preview.';
    if (!window.confirm('Kill this rejected provider result? Story Auto will not create a replacement automatically.')) return;
    await runAction('kill_elyum_preview','Killing the rejected provider result…',{request_id:button.dataset.requestId,confirm_kill:true,reason});
  }));
  document.querySelectorAll('[data-elyum-reacquire]').forEach(button => button.addEventListener('click', async () => {
    await runAction('keep_elyum_preview','Retrying clean output acquisition without another Keep…',{request_id:button.dataset.requestId,confirm_spend:false});
  }));
  document.querySelectorAll('[data-elyum-replace]').forEach(button => button.addEventListener('click', async () => {
    const surface = button.closest('.surface');
    const input = surface?.querySelector('[data-elyum-replacement-reason]');
    const promptInput = surface?.querySelector('[data-elyum-replacement-prompt]');
    const reason = input?.value?.trim() || '';
    const replacementPrompt = promptInput?.value?.trim() || '';
    if (!reason) { toast('Add a reason for the replacement attempt.',true); input?.focus(); return; }
    if (!replacementPrompt) { toast('Add the full revised provider prompt for this replacement.',true); promptInput?.focus(); return; }
    if (!window.confirm('Authorize exactly one new provider generation for this killed rejection? The previous attempt remains immutable.')) return;
    await runAction('authorize_elyum_replacement','Authorizing one replacement attempt…',{request_id:button.dataset.requestId,reason,confirm_replace:true,replacement_prompt:replacementPrompt});
  }));
}

function renderProject() {
  const workspace=state.snapshot, production=workspace.production, blocker=production.blocker, action=production.next_action, flow=production.flow;
  projectHeader(workspace);
  if (production.pipeline_status === 'COMPLETE') { syncActivityPresentation(); renderComplete(workspace); return; }
  const visual=production.stages.VISUALS || {}, recovery=production.recovery || {};
  const activeText=visual.status === 'RUNNING' && visual.total_items ? `Creating visuals — ${visual.completed_items} of ${visual.total_items}` : (blocker?.human_message || recovery.human_message || 'Completed stages are saved. Continue resumes the canonical production path.');
  syncActivityPresentation();
  const durableAction = canonicalBlockerAction(production);
  const immediateAction = durableAction || (state.actionOutcome?.kind === 'blocker' && state.actionOutcome.action_id ? {action:state.actionOutcome.action_id,label:state.actionOutcome.action} : action);
  const showActionOutcome = state.actionOutcome && !redundantSafetyOutcome(state.actionOutcome, production);
  const qualityPolicyRecovery = production.quality?.policy === 'AI_REVIEW'
    ? `<section class="surface" data-quality-policy-surface><div class="surface-head"><div><p class="eyebrow">QUALITY REVIEW</p><h2>Choose a supported review policy</h2><p>AI Review is reserved but is not runnable in this version. Choose the policy for this project so production can continue.</p></div></div><div class="button-row"><button class="button-primary" data-project-qc-policy="AUTO_ACCEPT" type="button" ${state.busy ? 'disabled' : ''}>Use Automatic</button><button data-project-qc-policy="MANUAL_REVIEW" type="button" ${state.busy ? 'disabled' : ''}>Use Manual review</button></div></section>`
    : '';
  const primary=`<button class="button-primary" data-project-action="${esc(immediateAction.action)}" type="button" ${state.busy ? 'disabled' : ''}>${esc(backendProductionWorking(production) ? 'Working…' : immediateAction.label)}</button>`;
  $('#view').innerHTML = `<section class="project-hero"><div><span class="status-chip ${blocker ? 'attention' : ''}">${esc(workspace.status)}</span><h2>${esc(workspace.title)}</h2><p>${esc(activeText)}</p>${stageMarkup(workspace)}</div><div class="progress-panel"><div class="progress-value"><span>${blocker ? 'Production status' : 'Current action'}</span><strong>${esc(immediateAction.label)}</strong></div><p>${esc(activeText)}</p>${blocker ? '<p class="hint">See the action needed below.</p>' : primary}</div></section>
  ${showActionOutcome ? actionOutcomeCard(state.actionOutcome) : ''}
  ${state.error ? errorCard(state.error) : ''}
  ${blocker ? `<section class="attention-card" aria-labelledby="blockerTitle"><div><h2 id="blockerTitle">${blocker.stage === 'PLAN' && production.pipeline_status === 'SAFETY_BLOCKED' ? 'Visual planning needs another attempt' : blocker.reason_code === 'STUCK_PENDING' ? 'Flow generation appears stuck' : 'Action needed'}</h2><p>${esc(blocker.human_message)}</p><p class="reassurance">Your completed work is saved.</p></div>${blocker.reason_code === 'STUCK_PENDING' ? '<div class="button-row"><button class="button-primary" data-project-action="recheck_flow_generation" type="button">Recheck status</button><button data-project-action="open_flow_project" type="button">Open Flow project</button></div>' : primary}${blocker.stage === 'PLAN' && production.pipeline_status === 'SAFETY_BLOCKED' ? `<details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(blocker.reason_code)}</div></details>` : ''}${flow?.status === 'PROJECT_MISMATCH' ? '<button data-rebind-flow type="button">Rebind this Story Auto project</button>' : ''}</section>` : ''}
  ${qualityPolicyRecovery}
  ${flow?.required && flow.status === 'CONNECTED' ? '<section class="surface"><p><strong>Flow:</strong> Connected</p></section>' : ''}
  ${fullVideoProviderSurface(workspace)}
  ${openingBuilderSurface(workspace)}
  ${hybridBodySurface(workspace)}
  <section class="surface"><div class="surface-head"><div><h2>Output and preview</h2><p>${workspace.final_path ? 'Your latest final video is ready.' : 'Your final video will appear here when production is complete.'}</p></div></div>${workspace.final_path ? `<a class="button button-primary" href="${assetUrl(workspace.project_id,workspace.final_path)}" target="_blank" rel="noopener">Open final video</a>` : '<div class="empty-library"><p>No final video yet.</p></div>'}</section>
  <section class="surface"><div class="surface-head"><div><h2>Project summary</h2><p>These are the effective settings saved with this project.</p></div></div><dl class="summary-list"><div class="summary-row"><dt>Source</dt><dd>${esc(workspace.summary.source)}</dd></div>${workspace.summary.narrator ? `<div class="summary-row"><dt>Narrator</dt><dd>${esc(workspace.summary.narrator)}</dd></div>` : ''}<div class="summary-row"><dt>Style</dt><dd>${esc(workspace.summary.style)}</dd></div><div class="summary-row"><dt>Quality review</dt><dd>${esc(workspace.summary.quality)}</dd></div><div class="summary-row"><dt>Waveform</dt><dd>${esc(workspace.summary.waveform)}</dd></div><div class="summary-row"><dt>Resolution</dt><dd>${esc(workspace.summary.resolution)}</dd></div></dl></section>
  <details class="surface disclosure"><summary>More actions</summary><div class="button-row">${production.active_stage === 'PLAN' ? '<button id="reviewPlan" type="button">Review plan</button>' : ''}<button id="reviewProject" type="button">Review visuals</button>${workspace.can_render_again ? '<button id="renderAgain" type="button">Render final video again</button>' : ''}</div></details>
  <details class="surface disclosure" id="projectDetails"><summary>Advanced, Diagnostics, and History</summary><div id="technicalContent" class="technical">Technical details load only when opened.</div></details>`;
  document.querySelectorAll('[data-project-action]').forEach(button => button.addEventListener('click', () => handleProjectAction(button.dataset.projectAction)));
  bindFullVideoProviderControls();
  bindOpeningBuilderControls();
  bindHybridBodyControls();
  document.querySelectorAll('[data-project-qc-policy]').forEach(button => button.addEventListener('click', () => {
    runAction('set_qc_policy','Updating this project’s quality review policy…',{policy:button.dataset.projectQcPolicy});
  }));
  document.querySelectorAll('[data-rebind-flow]').forEach(button => button.addEventListener('click', async () => {
    if (!window.confirm('Use the currently validated Flow project for future requests? Existing request history will remain unchanged.')) return;
    await runAction('rebind_flow_project','Rebinding future Flow requests…', {explicit_owner_decision:true});
  }));
  $('#reviewPlan')?.addEventListener('click', showPlanReview);
  $('#reviewProject')?.addEventListener('click', showReview);
  $('#renderAgain')?.addEventListener('click', () => runAction('render_again','Rendering the final video again…'));
  bindErrorActions();
  bindDiagnosticsDisclosure();
}

function canonicalBlockerAction(production) {
  const action = production?.next_action;
  return production?.blocker && typeof action?.action === 'string' && typeof action?.label === 'string' ? action : null;
}

function redundantSafetyOutcome(outcome, production) {
  const blocker = production?.blocker;
  return outcome?.outcome === 'SAFETY_BLOCKED'
    && Boolean(canonicalBlockerAction(production))
    && typeof blocker?.reason_code === 'string'
    && blocker.reason_code !== 'SAFETY_BLOCKED';
}

function renderComplete(snapshot) {
  $('#view').innerHTML = `<section class="success-banner"><p class="eyebrow">COMPLETE</p><h2>Your final video is ready.</h2><p>${esc(snapshot.title)} is complete. Production evidence remains available under Advanced.</p><div class="button-row"><a class="button button-primary" href="${assetUrl(snapshot.project_id,snapshot.final_path)}" target="_blank" rel="noopener">Open final video</a><button id="openFolder" type="button">Open folder</button><button id="renderAgain" type="button">Render again</button><button id="newVideoAfterComplete" type="button">Create another video</button></div></section><section class="surface"><h2>Final output</h2><video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,snapshot.final_path)}" aria-label="Final video preview"></video></section><details class="surface disclosure" id="projectDetails"><summary>Advanced, Diagnostics, and History</summary><div id="technicalContent" class="technical">Technical details load only when opened.</div></details>`;
  $('#openFolder').addEventListener('click', () => runAction('open_output','Opening the output folder…'));
  $('#renderAgain')?.addEventListener('click', () => runAction('render_again','Rendering the final video again…'));
  $('#newVideoAfterComplete')?.addEventListener('click', openWizard);
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
  if (action === 'choose_quality_policy') { document.querySelector('[data-quality-policy-surface]')?.scrollIntoView({behavior:'smooth',block:'start'}); return; }
  if (action === 'focus_opening_builder') { document.querySelector('.opening-slot-grid')?.scrollIntoView({behavior:'smooth',block:'start'}); return; }
  if (action === 'review_visuals' || action === 'review_project' || action === 'review_recovery' || action === 'open_final') return showReview();
  if (action === 'process' || action === 'run_to_final') return runAction('run_to_final','Continuing production until it needs your decision…');
  if (action === 'continue_production') return runAction('continue_production','Continuing production until it needs your decision…');
  if (action === 'validate_flow_connection') return runAction('validate_flow_connection','Validating the expected Flow project…');
  if (action === 'plan_visuals') return runAction('plan_visuals','Preparing the visual plan…');
  if (action === 'resume_generation') return runAction('resume_generation','Creating visuals. Completed work remains saved…');
  if (action === 'render') return runAction('render','Rendering the final video…');
  if (action === 'open_flow_sign_in') return runAction('open_flow_sign_in','Opening the Story Auto Flow sign-in window…');
  if (action === 'open_flow_project') return runAction('open_flow_project','Opening this video’s Flow project…');
  if (action === 'ensure_flow_project') return runAction('ensure_flow_project','Finishing this video’s Flow project setup…');
  if (action === 'recheck_flow_generation' || action === 'recheck_status') return runAction('recheck_flow_generation','Rechecking the exact Flow generation…');
  toast('This project action is not available in the current build. Review the project state before continuing.',true);
  return showReview();
}

async function runAction(action, label, extra = {}) {
  if (!state.project) return;
  if (state.busy || state.runToken) { toast('Another project action is still running.'); return; }
  const projectId = state.project;
  const token = Symbol(action); state.runToken = token; state.lastAction = {action,label};
  setBusy(true,label); state.error = null; state.actionOutcome = null; renderProject();
  let polling = false;
  const poll = setInterval(async () => {
    if (state.runToken !== token || polling) return;
    polling = true;
    try {
      const snapshot = await api(`/api/projects/${encodeURIComponent(projectId)}/workspace`);
      if (state.runToken === token && state.view === 'project' && state.project === projectId) { state.snapshot = snapshot; renderProject(); }
    }
    catch (_) { /* the primary request owns failure reporting */ }
    finally { polling = false; }
  },2500);
  try {
    const result = await api(`/api/projects/${encodeURIComponent(projectId)}/actions`,{method:'POST',body:JSON.stringify({action,...extra})});
    const snapshot = await api(`/api/projects/${encodeURIComponent(projectId)}/workspace`);
    if (state.runToken === token && state.view === 'project' && state.project === projectId) {
      state.snapshot = snapshot;
      state.actionOutcome = actionOutcome(result, snapshot);
    }
    const outcome = result?.outcome;
    toast(action === 'pause' ? 'Production will pause at the next safe point.' : action === 'open_flow_sign_in' ? 'Flow sign-in opened.' : outcome === 'FINAL_VIDEO_COMPLETE' ? 'Final video complete.' : outcome ? 'Production response received.' : 'Project updated.');
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
    if (!state.busy) { state.snapshot = await api(`/api/projects/${encodeURIComponent(state.project)}/workspace`); renderProject(); }
  } catch (error) { state.error = friendlyError(error); toast(state.error.title,true); if (!state.busy) renderProject(); }
}

function friendlyError(error) {
  const code = error?.payload?.failure_class || 'UNKNOWN_ERROR';
  const raw = error?.payload?.error || error?.message || code;
  const known = {
    FLOW_COOKIE_NO_EFFECT_PROOF_REQUIRED: ['Keep this Flow attempt', 'Saved evidence cannot prove that nothing was sent. Use Check / recover Flow video; no replacement will be generated.', 'focus_opening_builder', 'Review opening'],
    FLOW_COOKIE_ATTEMPT_IDENTITY_MISMATCH: ['The Flow session or inputs changed', 'This attempt keeps its original session revision, project and reference. Recover the original attempt; only unused setup with zero-effect proof can be reset.', 'focus_opening_builder', 'Review opening'],
    FLOW_COOKIE_SLOT_DURATION_UNSUPPORTED: ['Opening slot is too long for Flow', 'Flow reference video supports slots up to 8 seconds. Use another qualified provider or import a clip.', 'focus_opening_builder', 'Review opening'],
    FLOW_RPC_DISABLED: ['Flow generation is not enabled', 'This runtime is not enabled for the selected Flow project. No video was submitted. Saved cookie sessions can still be checked in Settings.', 'settings', 'Settings'],
    FLOW_COOKIE_PROJECT_INVALID: ['Check the Flow project address', 'Use the exact HTTPS Flow project address from your browser, without extra query parameters.', 'focus_opening_builder', 'Review opening'],
    STORY_TIMELINE_INVALID: ['Visual planning needs another attempt',"Story Auto couldn't produce a complete visual plan. Your audio and timing are saved. Try again.",'retry','Retry planning'],
    FLOW_AUTH_REQUIRED: ['Google sign-in required','Sign in to Google Flow, then return here and choose Try again.','open_flow_sign_in','Open Flow sign-in'],
    FLOW_CDP_UNAVAILABLE: ['Google Flow is not open','Open the dedicated Story Auto Flow window, sign in if needed, then try again.','open_flow_sign_in','Open Flow sign-in'],
    FLOW_PROJECT_MISMATCH: ['Flow project does not match','Story Auto could not confirm this video’s exact Flow project. Open the expected project and try again; no manual URL copy is required.','open_flow_project','Open expected Flow project'],
    FLOW_HOST_MIGRATED_RETRY_REQUIRED: ['Google Flow is switching interfaces','Google routed this session to the new Flow interface. Story Auto did not send a generation request; choose Try again so it can retry the compatible Flow workspace.','retry','Try again'],
    FLOW_NOT_CONFIGURED: ['Flow is not configured','Open this project and choose a Flow project URL. Validation does not create images or videos.','open_project','Open project'],
    FLOW_CONNECTION_STALE: ['Flow connection needs validation','The project points to an older Flow connection. Open the project and validate or update it before creating visuals.','open_project','Open project'],
    FLOW_CAPABILITY_UNAVAILABLE: ['Flow image generation is unavailable',"Story Auto could not confirm image generation in this video's live Flow editor. No request was sent.",'open_flow_project','Open Flow project'],
    STAGE_NO_PROGRESS: ['Production did not advance','Story Auto stopped before repeating the same stage. Refresh the project to review the saved recovery state before trying again.','open_project','Refresh project'],
    TIMELINE_ALIGNMENT_MISMATCH: ['Imported subtitle timing needs attention','Story Auto could not fit the imported subtitle timing to the narration timeline. Review the project before continuing.','review_project','Review project'],
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

function actionOutcome(result, snapshot) {
  const outcome = result?.outcome;
  if (!outcome) return null;
  const production = result.production && typeof result.production === 'object' ? result.production : {};
  const flow = result.flow && typeof result.flow === 'object' ? result.flow : (production.flow || {});
  const blocker = production.blocker && typeof production.blocker === 'object' ? production.blocker : {};
  const canonicalAction = flow.next_action || production.next_action || null;
  const code = result.reason_code || blocker.reason_code || outcome;
  if (outcome === 'FINAL_VIDEO_COMPLETE') return {kind:'success',title:'Final video complete',message:'Your final video is ready.',code,raw:''};
  if (outcome === 'SAFETY_BLOCKED') {
    const friendly = friendlyError({message:result.error || blocker.human_message || code,payload:{failure_class:code,error:result.error}});
    const planningFailure = blocker.stage === 'PLAN' || code === 'STORY_TIMELINE_INVALID';
    return {kind:'blocker',outcome,title:planningFailure ? 'Visual planning needs another attempt' : 'Production stopped safely',reason_title:planningFailure ? 'Your audio and timing are saved' : friendly.title,message:planningFailure ? (blocker.human_message || friendly.message) : friendly.message,code,raw:result.error || friendly.raw,action_id:planningFailure ? 'retry' : friendly.action_id,action:planningFailure ? 'Retry planning' : friendly.action};
  }
  if (outcome === 'OWNER_DECISION_REQUIRED') {
    return {kind:'blocker',title:'Your decision is needed',message:blocker.human_message || 'Review the saved production decision before Story Auto continues.',code,raw:'',action_id:canonicalAction?.action || 'review_project',action:canonicalAction?.label || blocker.next_action || 'Review project'};
  }
  if (outcome === 'NEEDS_ATTENTION') {
    return {kind:'blocker',title:'Production needs attention',message:blocker.human_message || production.recovery?.human_message || 'Review the saved recovery evidence before continuing.',code,raw:result.error || '',action_id:canonicalAction?.action || 'review_recovery',action:canonicalAction?.label || blocker.next_action || 'Review recovery'};
  }
  if (['BLOCKED','STUCK_PENDING','AUTH_REQUIRED','AUTH_RECOVERY_REQUIRED','NOT_CONFIGURED','STALE','PROJECT_MISMATCH','CAPABILITY_MISSING','PROJECT_SETUP_REQUIRED'].includes(outcome)) {
    return {kind:'blocker',title:'Flow needs attention',message:flow.human_message || 'Complete the required Flow recovery before continuing.',code,raw:result.error || '',action_id:canonicalAction?.action || 'settings',action:canonicalAction?.label || 'Review Flow'};
  }
  return {kind:'progress',title:'Production is continuing.',message:production.human_message || 'Story Auto saved this progress and refreshed the current production state.',code,raw:''};
}

function actionOutcomeCard(outcome) {
  const details = outcome.code ? `<details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(outcome.code)}${outcome.raw ? `\n${esc(outcome.raw)}` : ''}</div></details>` : '';
  return `<section class="attention-card action-outcome ${esc(outcome.kind)}" role="status"><div><h2>${esc(outcome.title)}</h2>${outcome.reason_title ? `<p><strong>${esc(outcome.reason_title)}</strong></p>` : ''}<p>${esc(outcome.message)}</p><p class="reassurance">Your completed work is saved.</p></div>${details}</section>`;
}

function bindErrorActions() {
  document.querySelectorAll('[data-error-action]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.errorAction;
    if (action === 'settings') return showSettings();
    if (action === 'open_flow_sign_in') return runAction('open_flow_sign_in','Opening the Story Auto Flow sign-in window…');
    if (action === 'open_flow_project') return runAction('open_flow_project','Opening this video’s Flow project…');
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
  const automatic = state.snapshot?.production?.quality?.policy === 'AUTO_ACCEPT';
  const prepareVisualPlan = !hasVisualPlan && automatic && approval === 'APPROVED';
  const names = kind => (continuity[kind] || []).map(item => item.name).filter(Boolean);
  setHeader('REVIEW PLAN',state.snapshot.title,'<button class="button-quiet" id="backProject" type="button">← Project</button>');
  $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><p class="eyebrow">BEFORE VISUAL CREATION</p><h2>${hasVisualPlan ? 'Review the visual plan' : 'Review the story plan'}</h2><p>Confirm the story structure before Story Auto begins the next costly stage.</p></div></div>
    <dl class="summary-list"><div class="summary-row"><dt>Characters</dt><dd>${esc(names('characters').join(', ') || 'No recurring characters detected')}</dd></div><div class="summary-row"><dt>Locations</dt><dd>${esc(names('locations').join(', ') || 'No recurring locations detected')}</dd></div><div class="summary-row"><dt>Scenes</dt><dd>${shots.length || planning.story_timeline?.scenes?.length || 0}</dd></div><div class="summary-row"><dt>Production style</dt><dd>${esc(humanMode(state.snapshot.render_mode))}</dd></div></dl>
    <div class="next-action" style="margin-top:22px"><div><h2>${hasVisualPlan ? 'Approve visual plan' : prepareVisualPlan ? 'Prepare visual plan' : 'Approve and prepare visuals'}</h2><p>${hasVisualPlan ? 'This allows Story Auto to begin creating the planned scenes.' : 'Story Auto will turn this approved story structure into a visual plan.'}</p></div><button class="button-primary" id="approveCurrentPlan" type="button">${hasVisualPlan ? 'Approve visual plan' : prepareVisualPlan ? 'Prepare visual plan' : 'Approve story plan'}</button></div>
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
    const manualPolicy = state.snapshot?.production?.quality?.policy === 'MANUAL_REVIEW';
    const pendingCount = review.issues.filter(issue => issue.status === 'QC_PENDING').length;
    const manualBatch = manualPolicy && pendingCount ? `<section class="surface"><div class="surface-head"><div><h2>Accept eligible visuals</h2><p>Accept all technically valid pending visuals and continue production. This records your decision against each exact asset.</p></div></div><div class="field"><label for="manualBatchReason">Reason for accepting this batch</label><input id="manualBatchReason" type="text" autocomplete="off" placeholder="Why these visuals are ready to use"></div><div class="button-row"><button class="button-primary" id="acceptManualBatch" type="button">Accept ${pendingCount} eligible visual${pendingCount === 1 ? '' : 's'}</button></div></section>` : '';
    $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><h2>Quality review</h2><p>${review.final_path ? `Final duration ${esc(formatDuration(review.duration_seconds))}.` : 'Review flagged scenes before production continues.'}</p></div>${review.final_path ? `<a class="button button-primary" href="${assetUrl(state.project,review.final_path)}" target="_blank" rel="noopener">Open final video</a>` : ''}</div>${qualityCards(review.quality)}</section>
      ${manualBatch}${review.final_path ? `<section class="surface review-layout"><video class="video-frame" controls preload="metadata" src="${assetUrl(state.project,review.final_path)}" aria-label="Final video review"></video><aside class="review-sidebar"><h3>Publishing package</h3><p><strong>${esc(publishing.selected_title || review.title)}</strong></p><p class="publishing-copy">${esc(publishing.description || 'Publishing copy has not been prepared yet.')}</p>${publishing.description ? '<button id="copyPublishing" type="button">Copy title & description</button>' : ''}</aside></section>` : ''}
      <section class="surface"><div class="surface-head"><div><h2>Items needing review</h2><p>${review.issues.length ? `${review.issues.length} item${review.issues.length === 1 ? ' needs' : 's need'} a decision.` : 'No remaining quality issues were found.'}</p></div></div><div class="issue-list">${issues || '<div class="empty-library"><strong>Quality checks are clear.</strong><p>No item needs your attention.</p></div>'}</div></section>`;
    $('#backProject').addEventListener('click', () => openProject(state.project));
    $('#copyPublishing')?.addEventListener('click', async () => { await navigator.clipboard.writeText(`${publishing.selected_title || review.title}\n\n${publishing.description}`); toast('Title and description copied.'); });
    $('#acceptManualBatch')?.addEventListener('click', async () => {
      const reason=$('#manualBatchReason').value.trim();
      if (!reason) { toast('Add a reason for accepting this batch.',true); $('#manualBatchReason').focus(); return; }
      const button=$('#acceptManualBatch'); button.disabled=true;
      try { const result=await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'accept_selected_assets',reason})}); toast(`${result.accepted_assets || 0} visual${result.accepted_assets === 1 ? '' : 's'} accepted.`); await openProject(state.project); }
      catch (error) { toast(friendlyError(error).message,true); button.disabled=false; }
    });
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
  const defaults = state.settings.defaults;
  const selectedDefaultVoice = hasInstalledVoice(defaults.voice_id) ? defaults.voice_id : '';
  const narratorMessage = state.settings.defaults.narrator_message || (installedVoices().length ? '' : 'No installed Kokoro narrators are available. Configure Kokoro before creating a video.');
  const providerRows = state.settings.providers.map(provider => `<div class="provider-row"><div><strong>${esc(provider.name)}</strong><small>${esc(provider.detail)}</small></div><span class="provider-state ${provider.status !== 'Ready' ? 'attention' : ''}">${esc(provider.status)}</span></div>`).join('');
  const flow = state.settings.flow_connection || {};
  const flowCookie = state.settings.flow_cookie || {};
  const flowCookieAccounts = flowCookie.accounts || [];
  const flowCookieDetails = `<section class="settings-section" aria-labelledby="flowCookieHeading">
    <p class="eyebrow">EXPERIMENTAL · REFERENCE VIDEO</p><h2 id="flowCookieHeading">Flow cookie session</h2>
    <p>Save a session without keeping your own Chrome window open. Saving or testing does not generate video or switch existing projects.</p>
    <p>${esc(flowCookieAccounts.length ? `${flowCookieAccounts.length} saved session(s) · Configured, not checked` : flowCookie.status === 'NEEDS_ATTENTION' ? 'Saved sessions could not be read. Check local credential storage before continuing.' : 'No sessions saved. Choose a Cookie Editor JSON export to begin.')}</p>
    <div class="settings-grid"><div class="field"><label for="flowCookieName">Session name</label><input id="flowCookieName" autocomplete="off" maxlength="80" placeholder="daily"><small>Use the same name to refresh its cookie. This creates a new revision; existing attempts never switch revisions silently.</small></div>
    <div class="field"><label for="flowCookieFile">Cookie JSON file</label><input id="flowCookieFile" type="file" accept=".json,.txt,application/json"><small>Encrypted for this Windows user. Cookie values are never shown again or saved in project files.</small></div></div>
    <div class="button-row"><button id="previewFlowCookie" type="button">Preview session</button><button id="saveFlowCookie" type="button">Save session</button></div>
    <hr><div class="settings-grid"><div class="field"><label for="flowCookieAccount">Saved session</label><select id="flowCookieAccount" ${flowCookieAccounts.length ? '' : 'disabled'}>${flowCookieAccounts.length ? flowCookieAccounts.map(a=>`<option value="${esc(a.account_id)}">${esc(a.account_id)} · revision ${esc(a.revision)}</option>`).join('') : '<option>No saved sessions</option>'}</select></div>
    <div class="field"><label for="flowCookieProject">Flow project URL</label><input id="flowCookieProject" type="url" placeholder="https://flow.google.com/project/..."><small>Open the target project in Flow and copy its address. This check only reads access.</small></div></div>
    <div class="button-row"><button id="testFlowCookie" type="button" ${flowCookieAccounts.length ? '' : 'disabled'}>Test connection</button><button id="removeFlowCookie" type="button" ${flowCookieAccounts.length ? '' : 'disabled'}>Remove saved session</button></div>
    ${flowCookieAccounts.length ? '' : '<small>Save a session first to enable the connection check.</small>'}
    <p id="flowCookieStatus" role="status" aria-live="polite"></p>
  </section>`;
  const byteplus = state.settings.byteplus || {};
  const elyum = state.settings.elyum || {};
  const pexels = state.settings.pexels || {};
  const externalLlm = state.settings.external_llm || {};
  const dola = state.settings.dola || {};
  const videoProviders = state.settings.video_providers || [];
  const flowLabel = {CONNECTED:'Flow session ready',NOT_CONFIGURED:'Open Flow to connect',AUTH_REQUIRED:'Sign in to Flow to continue',STALE:'Flow session needs confirmation',PROJECT_MISMATCH:'Flow session needs confirmation',CAPABILITY_MISSING:'Flow image creation is unavailable'}[flow.status] || 'Open Flow to connect';
  const flowDetails = `<section class="settings-section"><h2>Flow session</h2><p>Story Auto uses its dedicated Chrome profile and automatically creates one Flow project for each new video.</p><dl class="summary-list"><div class="summary-row"><dt>Status</dt><dd>${esc(flowLabel)}</dd></div><div class="summary-row"><dt>Browser profile</dt><dd>Dedicated Story Auto session</dd></div><div class="summary-row"><dt>Validated capabilities</dt><dd>${esc(Object.entries(flow.observed_capabilities || {}).filter(([,ok]) => ok).map(([name]) => name).join(', ') || 'Not checked')}</dd></div></dl></section>`;
  const byteplusState = byteplus.configured ? (byteplus.live_verified ? 'Connected' : 'Configured') : 'Not configured';
  const byteplusHelp = byteplus.configured ? 'BytePlus can generate Hybrid opening clips and Full Video tasks. Test connection performs a read-only task-list check.' : 'Add a BytePlus ModelArk API key to enable Generate with API for Hybrid opening slots. Manual import remains available without it.';
  const byteplusDetails = `<section class="settings-section"><h2>Opening API video · BytePlus</h2><p>${esc(byteplusHelp)}</p><dl class="summary-list"><div class="summary-row"><dt>Status</dt><dd id="byteplusLiveStatus">${esc(byteplusState)}</dd></div><div class="summary-row"><dt>Model</dt><dd>${esc(byteplus.model || 'Seedance')}</dd></div><div class="summary-row"><dt>Saved keys</dt><dd>${esc(byteplus.saved_credential_count ?? 0)}</dd></div><div class="summary-row"><dt>Credential storage</dt><dd>${esc(byteplus.credential_source === 'ENVIRONMENT' ? 'Environment variable' : byteplus.configured ? 'Windows DPAPI · current user' : 'Not configured')}</dd></div></dl><div class="field" style="margin-top:16px"><label for="byteplusApiKey">BytePlus ModelArk API keys</label><textarea id="byteplusApiKey" rows="4" autocomplete="off" spellcheck="false" placeholder="Paste one key per line. New keys are appended; duplicates are ignored."></textarea><small>Keys are encrypted with Windows DPAPI and are never stored in a project or repository.</small></div><div class="button-row" style="margin-top:14px"><button id="saveByteplusKey" type="button">Add keys</button><button id="testByteplusKey" type="button" ${byteplus.configured ? '' : 'disabled'}>Test connection</button><button id="clearByteplusKey" class="button-quiet" type="button" ${byteplus.removable ? '' : 'disabled'}>Remove saved keys</button></div></section>`;
  const elyumState = elyum.configured ? (elyum.live_verified ? 'Connected' : 'Configured') : 'Not configured';
  const elyumHelp = elyum.configured ? 'Test connection reads the Elyum account/model catalog and verifies Seedance text-to-video with a no-generation cost estimate. Hybrid Opening generation stays gated until that succeeds.' : 'Add an Elyum API key to prepare the secondary Seedance provider. This does not enable generation automatically.';
  const elyumDetails = `<section class="settings-section"><h2>Opening API video · Elyum</h2><p>${esc(elyumHelp)}</p><dl class="summary-list"><div class="summary-row"><dt>Status</dt><dd id="elyumLiveStatus">${esc(elyumState)}</dd></div><div class="summary-row"><dt>Transport</dt><dd>${esc(elyum.transport || 'MCP Streamable HTTP')}</dd></div><div class="summary-row"><dt>Seedance T2V preflight</dt><dd id="elyumModelStatus">Not checked</dd></div><div class="summary-row"><dt>Saved keys</dt><dd>${esc(elyum.saved_credential_count ?? 0)}</dd></div><div class="summary-row"><dt>Credential storage</dt><dd>${esc(elyum.credential_source === 'ENVIRONMENT' ? 'Environment variable' : elyum.configured ? 'Windows DPAPI · current user' : 'Not configured')}</dd></div></dl><div class="field" style="margin-top:16px"><label for="elyumApiKey">Elyum API keys</label><textarea id="elyumApiKey" rows="4" autocomplete="off" spellcheck="false" placeholder="Paste one key per line. New keys are appended; duplicates are ignored."></textarea><small>Keys are encrypted with Windows DPAPI and are never stored in a project or repository.</small></div><div class="button-row" style="margin-top:14px"><button id="saveElyumKey" type="button">Add keys</button><button id="testElyumKey" type="button" ${elyum.configured ? '' : 'disabled'}>Test connection</button><button id="clearElyumKey" class="button-quiet" type="button" ${elyum.removable ? '' : 'disabled'}>Remove saved keys</button></div></section>`;
  const pexelsState = pexels.configured ? (pexels.live_verified ? 'Connected' : 'Configured') : 'Not configured';
  const pexelsHelp = pexels.configured ? 'Pexels can supply semantic stock clips. Use Test connection for a live no-download API check.' : 'Add a Pexels API key to enable semantic stock clips. Hybrid Visual still works without it by using image fallback.';
  const pexelsDetails = `<section class="settings-section"><h2>Hybrid stock video · Pexels</h2><p>${esc(pexelsHelp)}</p><dl class="summary-list"><div class="summary-row"><dt>Status</dt><dd id="pexelsLiveStatus">${esc(pexelsState)}</dd></div><div class="summary-row"><dt>Fallback</dt><dd>Generated image</dd></div><div class="summary-row"><dt>Saved keys</dt><dd>${esc(pexels.saved_credential_count ?? 0)}</dd></div><div class="summary-row"><dt>Credential storage</dt><dd>${esc(pexels.credential_source === 'ENVIRONMENT' ? 'Environment variable' : pexels.configured ? 'Windows DPAPI · current user' : 'Not configured')}</dd></div></dl><div class="field" style="margin-top:16px"><label for="pexelsApiKey">Pexels API keys</label><textarea id="pexelsApiKey" rows="4" autocomplete="off" spellcheck="false" placeholder="Paste one key per line. New keys are appended; duplicates are ignored."></textarea><small>Keys are encrypted with Windows DPAPI and are never stored in a project or repository.</small></div><div class="button-row" style="margin-top:14px"><button id="savePexelsKey" type="button">Add keys</button><button id="testPexelsKey" type="button" ${pexels.configured ? '' : 'disabled'}>Test connection</button><button id="clearPexelsKey" class="button-quiet" type="button" ${pexels.removable ? '' : 'disabled'}>Remove saved keys</button></div></section>`;
  const brainProvider = state.settings.creation_defaults?.llm?.provider || 'gemini';
  const externalState = externalLlm.configured ? (externalLlm.live_verified ? 'Connected' : 'Configured') : 'Not configured';
  const externalLlmDetails = `<section class="settings-section"><p class="eyebrow">AI BRAIN</p><h2>Reasoning provider</h2><p>Gemini 3.8 is the production baseline. You can instead route new projects through any gateway that implements the Anthropic Messages API. Existing projects keep their saved provider.</p><dl class="summary-list"><div class="summary-row"><dt>Default for new projects</dt><dd id="brainProviderStatus">${esc(brainProvider === 'external_anthropic' ? 'External Anthropic-compatible gateway' : 'Gemini 3.8 Flash')}</dd></div><div class="summary-row"><dt>External status</dt><dd id="externalLlmLiveStatus">${esc(externalState)}</dd></div><div class="summary-row"><dt>Saved external keys</dt><dd>${esc(externalLlm.saved_credential_count ?? 0)}</dd></div></dl><div class="settings-grid"><div class="field"><label for="externalLlmBaseUrl">Gateway base URL</label><input id="externalLlmBaseUrl" type="url" value="${esc(externalLlm.base_url || '')}" placeholder="https://gateway.example.com or https://gateway.example.com/anthropic"><small>Use the API base URL, not the shop/account page. Story Auto appends /v1/messages.</small></div><div class="field"><label for="externalLlmModel">Model alias</label><input id="externalLlmModel" type="text" value="${esc(externalLlm.model_alias || '')}" placeholder="claude-sonnet-4-5 or gateway alias"></div><div class="field"><label for="externalLlmAuthMode">Authentication</label><select id="externalLlmAuthMode"><option value="x-api-key" ${externalLlm.auth_mode !== 'bearer' ? 'selected' : ''}>x-api-key</option><option value="bearer" ${externalLlm.auth_mode === 'bearer' ? 'selected' : ''}>Authorization: Bearer</option></select></div></div><div class="field" style="margin-top:16px"><label for="externalLlmApiKey">External gateway API keys</label><textarea id="externalLlmApiKey" rows="4" autocomplete="off" spellcheck="false" placeholder="Paste one key per line. New keys are appended; duplicates are ignored."></textarea><small>Keys are encrypted with Windows DPAPI. Base URL/model/auth mode are non-secret defaults for future projects.</small></div><div class="button-row" style="margin-top:14px"><button id="useGeminiBrain" type="button">Use Gemini 3.8</button><button id="saveExternalLlmConfig" type="button">Use external gateway</button><button id="saveExternalLlmKeys" type="button">Add gateway keys</button><button id="testExternalLlm" type="button" ${externalLlm.credential_configured && externalLlm.base_url && externalLlm.model_alias ? '' : 'disabled'}>Test connection</button><button id="clearExternalLlmKeys" class="button-quiet" type="button" ${externalLlm.removable ? '' : 'disabled'}>Remove saved keys</button></div><small>Gateway model names are aliases reported by that gateway. Story Auto does not claim they prove the upstream vendor/model identity.</small></section>`;
  const videoProviderRows = videoProviders.map(provider => `<div class="provider-row"><div><strong>${esc(provider.display_name)}</strong><small>Tier ${esc(provider.tier)} · ${esc(provider.model_family)} · ${esc(provider.transport)} · ${esc(provider.lifecycle)}</small></div><span class="provider-state ${provider.status !== 'READY' ? 'attention' : ''}">${esc(provider.experimental ? 'Experimental' : provider.production_routed ? provider.status : `${provider.status} · not routed`)}</span></div>`).join('');
  const videoProviderDetails = `<section class="settings-section"><h2>Video generation providers</h2><p>Capability-first registry. Model family and provider are separate; provider-specific lifecycle stays inside each adapter.</p><div class="provider-list">${videoProviderRows}</div><small>Provider switching is allowed only before a confirmed or ambiguous external dispatch. Manual external generation remains available for Hybrid Opening.</small></section>`;
  const dolaAccounts = Array.isArray(dola.accounts) ? dola.accounts : [];
  const dolaRows = dolaAccounts.length
    ? dolaAccounts.map(account => `<div class="provider-row"><div><strong>${esc(account.account_id)}</strong><small>Cookie saved on this Windows user account.</small></div><button class="button-quiet" type="button" data-remove-dola-account="${esc(account.account_id)}">Remove</button></div>`).join('')
    : '<p class="hint">No Dola accounts are saved.</p>';
  const dolaDetails = `<section class="settings-section"><p class="eyebrow">EXPERIMENTAL VIDEO PROVIDER</p><h2>Dola accounts</h2><p>Paste a fresh browser export when an account needs renewal. Saving the same account name refreshes only that account.</p><dl class="summary-list"><div class="summary-row"><dt>Status</dt><dd>${esc(dola.configured ? 'Configured' : 'Not configured')}</dd></div><div class="summary-row"><dt>Saved accounts</dt><dd>${esc(dola.account_count || 0)}</dd></div><div class="summary-row"><dt>Connection check</dt><dd>Not checked</dd></div></dl><div class="provider-list" style="margin-top:14px">${dolaRows}</div><div class="field" style="margin-top:16px"><label for="dolaAccountName">Account name for Cookie-Editor export</label><input id="dolaAccountName" type="text" value="dola-main" autocomplete="off" autocapitalize="off" spellcheck="false"><small>Used when you paste the raw JSON export below. Preview shows whether this name is new or will be updated.</small></div><div class="field" style="margin-top:16px"><label for="dolaAccountsInput">Dola cookies</label><textarea id="dolaAccountsInput" rows="5" autocomplete="off" spellcheck="false" placeholder="Paste Cookie-Editor JSON from www.dola.com"></textarea><small>Paste the full Cookie-Editor JSON array directly. Advanced: named headers as account-name[TAB]cookie header, one per line, or JSON [{"account_id":"name","cookie":"full cookie"}]. Cookies are encrypted for this Windows user and never shown again.</small></div><div id="dolaPreview" class="hint" aria-live="polite"></div><div class="button-row" style="margin-top:14px"><button id="previewDolaAccounts" type="button">Preview changes</button><button id="saveDolaAccounts" class="button-primary" type="button">Save accounts</button></div></section>`;
  const projectOptions = state.projects.map(project => `<option value="${esc(project.project_id)}">${esc(project.title)}</option>`).join('');
  $('#view').innerHTML = `<div class="settings-layout">
    <section class="settings-section"><p class="eyebrow">DEFAULT FOR NEW PROJECTS</p><h2>General defaults</h2><p>These durable defaults apply only when you create a new video. Existing projects keep their saved settings.</p><div class="settings-grid"><div class="field"><label for="defaultMode">Default output style</label><select id="defaultMode"><option value="full_image" selected>Full Image</option><option value="hybrid_hook" disabled>Hybrid Visual — choose per video</option><option value="full_video_ai" disabled>Full Video — choose per video</option></select><small>Full Image is the only global default. Hybrid Visual and Full Video remain available when creating an individual video.</small></div><div class="field"><label for="defaultVoice">Default narrator</label><select id="defaultVoice" ${installedVoices().length ? '' : 'disabled'}>${voiceOptions(selectedDefaultVoice)}</select>${narratorMessage ? `<small class="field-error">${esc(narratorMessage)}</small>` : ''}</div><div class="field"><label for="defaultQuality">Default Quality Review</label><select id="defaultQuality"><option value="AUTO_ACCEPT" ${state.settings.creation_defaults.qc_policy === 'AUTO_ACCEPT' ? 'selected' : ''}>Automatic</option><option value="MANUAL_REVIEW" ${state.settings.creation_defaults.qc_policy === 'MANUAL_REVIEW' ? 'selected' : ''}>Manual</option></select></div><label class="choice"><input id="defaultWaveform" type="checkbox" ${state.settings.creation_defaults.full_image?.audio_visualizer !== false ? 'checked' : ''}><strong>Waveform</strong><small>Show by default for Full Image projects.</small></label></div><div class="button-row" style="margin-top:18px"><button class="button-primary" id="saveDefaults" type="button" ${installedVoices().length ? '' : 'disabled'}>Save defaults</button></div></section>
    <section class="settings-section"><h2>Connections</h2><p>Human-level readiness for the services Story Auto can use.</p><div class="provider-list">${providerRows}</div></section>
    ${videoProviderDetails}
    ${dolaDetails}
    ${externalLlmDetails}
    ${flowDetails}
    ${flowCookieDetails}
    ${byteplusDetails}
    ${elyumDetails}
    ${pexelsDetails}
    <section class="settings-section"><h2>Storage</h2><p>Story Auto keeps projects and generated media in its isolated local workspace.</p><dl class="summary-list"><div class="summary-row"><dt>Project location</dt><dd>${esc(state.settings.storage.project_location)}</dd></div><div class="summary-row"><dt>Free space</dt><dd>${state.settings.storage.free_gb} GB</dd></div></dl></section>
    <section class="settings-section"><h2>Advanced</h2><p>Technical configuration and diagnostics for troubleshooting.</p><details class="disclosure"><summary>Provider details</summary><dl class="summary-list"><div class="summary-row"><dt>Voice provider</dt><dd>${esc(state.settings.advanced.tts_provider)}</dd></div>${state.settings.advanced.kokoro_readiness ? `<div class="summary-row"><dt>Kokoro readiness</dt><dd>${esc(state.settings.advanced.kokoro_readiness.technical_code || state.settings.advanced.kokoro_readiness.state)}</dd></div>` : ''}<div class="summary-row"><dt>Gemini model</dt><dd>${esc(state.settings.advanced.gemini_model)}</dd></div><div class="summary-row"><dt>Flow project</dt><dd>${esc(state.settings.advanced.flow_project)}</dd></div><div class="summary-row"><dt>Runtime root</dt><dd>${esc(state.settings.advanced.runtime_root)}</dd></div></dl></details>
      <details class="disclosure"><summary>Diagnostics</summary><div class="field"><label for="diagnosticProject">Project</label><select id="diagnosticProject">${projectOptions || '<option value="">No projects available</option>'}</select><small>Diagnostics may include internal IDs, exact paths, manifests, provider attempts, and raw status codes.</small></div><button id="openDiagnostics" type="button" style="margin-top:14px" ${projectOptions ? '' : 'disabled'}>Open diagnostics</button></details>
    </section>
  </div>`;
  if (dola.cookie_editor_import_supported !== true) {
    for (const selector of ['#dolaAccountName', '#dolaAccountsInput', '#previewDolaAccounts', '#saveDolaAccounts']) {
      const control = $(selector); if (control) control.disabled = true;
    }
    const target = $('#dolaPreview');
    if (target) target.textContent = 'This Story Auto window is running an older server. Open the updated window before importing Dola cookies. Nothing has been saved here.';
  }
  $('#saveDefaults').addEventListener('click', async () => { const voiceId=$('#defaultVoice').value; if (!hasInstalledVoice(voiceId)) { toast('Choose an installed narrator before saving defaults.',true); return; } try { state.settings=await api('/api/settings/defaults',{method:'POST',body:JSON.stringify({defaults:{render_mode:$('#defaultMode').value,ambient_style:$('#defaultAmbientStyle').value,narrator:{voice_id:voiceId},project_settings:{qc_policy:$('#defaultQuality').value,full_image:{audio_visualizer:$('#defaultWaveform').checked}}}})}); state.creationDefaults=null; toast('Defaults saved for new projects.'); await showSettings(); } catch (error) { toast(friendlyError(error).message,true); } });
  $('#saveByteplusKey')?.addEventListener('click', async () => {
    const keys=$('#byteplusApiKey').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (!keys.length) { toast('Paste one or more BytePlus ModelArk API keys, one per line.',true); $('#byteplusApiKey').focus(); return; }
    try { const result=await api('/api/settings/byteplus/save',{method:'POST',body:JSON.stringify({keys})}); $('#byteplusApiKey').value=''; toast(`Added ${result.added_count || 0} BytePlus key(s). ${result.saved_credential_count ?? result.saved_count ?? 0} saved.`); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#testByteplusKey')?.addEventListener('click', async event => {
    const button=event.currentTarget; button.disabled=true; button.textContent='Testing...';
    try {
      const result=await api('/api/settings/byteplus/test',{method:'POST',body:'{}'});
      const target=$('#byteplusLiveStatus');
      if (target) target.textContent=result.status === 'CONNECTED' ? 'Connected' : (result.reason_code || result.status);
      toast(result.status === 'CONNECTED' ? 'BytePlus connection verified.' : `BytePlus test: ${result.reason_code || result.status}`, result.status !== 'CONNECTED');
    } catch (error) { toast(friendlyError(error).message,true); }
    finally { button.disabled=false; button.textContent='Test connection'; }
  });
  $('#clearByteplusKey')?.addEventListener('click', async () => {
    try { await api('/api/settings/byteplus/clear',{method:'POST',body:'{}'}); toast('Saved BytePlus keys removed.'); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#saveElyumKey')?.addEventListener('click', async () => {
    const keys=$('#elyumApiKey').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (!keys.length) { toast('Paste one or more Elyum API keys, one per line.',true); $('#elyumApiKey').focus(); return; }
    try { const result=await api('/api/settings/elyum/save',{method:'POST',body:JSON.stringify({keys})}); $('#elyumApiKey').value=''; toast(`Added ${result.added_count || 0} Elyum key(s). ${result.saved_credential_count ?? result.saved_count ?? 0} saved.`); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#testElyumKey')?.addEventListener('click', async event => {
    const button=event.currentTarget; button.disabled=true; button.textContent='Testing...';
    try {
      const result=await api('/api/settings/elyum/test',{method:'POST',body:'{}'});
      const target=$('#elyumLiveStatus'); if (target) target.textContent=result.status === 'CONNECTED' ? 'Connected' : (result.reason_code || result.status);
      const modelTarget=$('#elyumModelStatus');
      if (modelTarget) modelTarget.textContent=result.status === 'CONNECTED'
        ? (result.seedance_t2v_models || []).map(item => `${item.model_id} (${item.estimated_credits_6s} credits/6s @ 480p)`).join(', ')
        : 'Not verified';
      toast(result.status === 'CONNECTED' ? 'Elyum Seedance T2V preflight verified.' : `Elyum test: ${result.reason_code || result.status}`, result.status !== 'CONNECTED');
    } catch (error) { toast(friendlyError(error).message,true); }
    finally { button.disabled=false; button.textContent='Test connection'; }
  });
  $('#clearElyumKey')?.addEventListener('click', async () => {
    try { await api('/api/settings/elyum/clear',{method:'POST',body:'{}'}); toast('Saved Elyum keys removed.'); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#savePexelsKey')?.addEventListener('click', async () => {
    const keys=$('#pexelsApiKey').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (!keys.length) { toast('Paste one or more Pexels API keys, one per line.',true); $('#pexelsApiKey').focus(); return; }
    try { const result=await api('/api/settings/pexels/save',{method:'POST',body:JSON.stringify({keys})}); $('#pexelsApiKey').value=''; toast(`Added ${result.added_count || 0} Pexels key(s). ${result.saved_credential_count ?? result.saved_count ?? 0} saved.`); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#testPexelsKey')?.addEventListener('click', async event => {
    const button=event.currentTarget; button.disabled=true; button.textContent='Testing…';
    try {
      const result=await api('/api/settings/pexels/test',{method:'POST',body:'{}'});
      const target=$('#pexelsLiveStatus');
      if (target) target.textContent=result.status === 'CONNECTED'
        ? `Connected${Number.isFinite(result.rate_limit?.remaining) ? ` · ${result.rate_limit.remaining} requests remaining` : ''}`
        : (result.reason_code || result.status);
      toast(result.status === 'CONNECTED' ? 'Pexels connection verified.' : `Pexels test: ${result.reason_code || result.status}`, result.status !== 'CONNECTED');
    } catch (error) { toast(friendlyError(error).message,true); }
    finally { button.disabled=false; button.textContent='Test connection'; }
  });
  $('#clearPexelsKey')?.addEventListener('click', async () => {
    try { await api('/api/settings/pexels/clear',{method:'POST',body:'{}'}); toast('Saved Pexels keys removed.'); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#useGeminiBrain')?.addEventListener('click', async () => {
    try { await api('/api/settings/brain/gemini',{method:'POST',body:'{}'}); toast('Gemini 3.8 Flash selected for new projects.'); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#saveExternalLlmConfig')?.addEventListener('click', async () => {
    const base_url=$('#externalLlmBaseUrl').value.trim(); const model_alias=$('#externalLlmModel').value.trim(); const auth_mode=$('#externalLlmAuthMode').value;
    if (!base_url || !model_alias) { toast('Enter both gateway base URL and model alias.',true); return; }
    try { await api('/api/settings/external-llm/configure',{method:'POST',body:JSON.stringify({base_url,model_alias,auth_mode})}); toast('External gateway selected for new projects.'); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#saveExternalLlmKeys')?.addEventListener('click', async () => {
    const keys=$('#externalLlmApiKey').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (!keys.length) { toast('Paste one or more external gateway API keys, one per line.',true); return; }
    try { const result=await api('/api/settings/external-llm/save',{method:'POST',body:JSON.stringify({keys})}); $('#externalLlmApiKey').value=''; toast(`Added ${result.added_count || 0} gateway key(s). ${result.saved_credential_count ?? result.saved_count ?? 0} saved.`); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  $('#testExternalLlm')?.addEventListener('click', async event => {
    const button=event.currentTarget; button.disabled=true; button.textContent='Testing...';
    try { const result=await api('/api/settings/external-llm/test',{method:'POST',body:'{}'}); const target=$('#externalLlmLiveStatus'); if (target) target.textContent=result.status === 'CONNECTED' ? `Connected${result.gateway_reported_model ? ` · ${result.gateway_reported_model}` : ''}` : (result.reason_code || result.status); toast(result.status === 'CONNECTED' ? 'External gateway connection verified.' : `External gateway test: ${result.reason_code || result.status}`, result.status !== 'CONNECTED'); }
    catch (error) { toast(friendlyError(error).message,true); }
    finally { button.disabled=false; button.textContent='Test connection'; }
  });
  $('#clearExternalLlmKeys')?.addEventListener('click', async () => {
    try { await api('/api/settings/external-llm/clear',{method:'POST',body:'{}'}); toast('Saved external gateway keys removed.'); await showSettings(); }
    catch (error) { toast(friendlyError(error).message,true); }
  });
  let flowCookieBusy = false;
  async function flowCookieAction(message, work) {
    if (flowCookieBusy) return;
    flowCookieBusy = true;
    const controls = ['previewFlowCookie','saveFlowCookie','testFlowCookie','removeFlowCookie'].map(id=>$('#'+id));
    const previous = controls.map(button=>button.disabled);
    const previousFocus = document.activeElement;
    const status = $('#flowCookieStatus'); status.textContent = message;
    controls.forEach(button=>button.disabled=true);
    try { await work(status); }
    catch (error) {
      const localMessages = [
        'Enter a session name and choose a cookie JSON file.',
        'Cookie file is too large (maximum 1 MB).',
      ];
      status.textContent = localMessages.includes(error.message) ? error.message : friendlyError(error).message;
      toast(status.textContent,true);
    }
    finally {
      flowCookieBusy=false;
      controls.forEach((button,i)=>button.disabled=previous[i]);
      if (previousFocus?.isConnected) previousFocus.focus();
    }
  }
  async function flowCookieDraft() {
    const account_id = $('#flowCookieName').value.trim();
    const file = $('#flowCookieFile').files[0];
    if (!account_id || !file) throw new Error('Enter a session name and choose a cookie JSON file.');
    if (file.size > 1024*1024) throw new Error('Cookie file is too large (maximum 1 MB).');
    return {account_id,cookies:await file.text()};
  }
  $('#previewFlowCookie').addEventListener('click',()=>flowCookieAction('Checking import...',async status=>{
    const draft = await flowCookieDraft();
    const preview = await api('/api/settings/flow-cookie/preview',{method:'POST',body:JSON.stringify(draft)});
    status.textContent = `${preview.replacing ? 'Refresh' : 'Add'} session "${draft.account_id}". No generation or project change. Select Save session to confirm.`;
  }));
  $('#saveFlowCookie').addEventListener('click',()=>flowCookieAction('Checking import...',async status=>{
    const draft = await flowCookieDraft();
    const preview = await api('/api/settings/flow-cookie/preview',{method:'POST',body:JSON.stringify(draft)});
    if (!await confirmFlowAction(`${preview.replacing ? 'Refresh' : 'Save'} Flow session "${draft.account_id}" for this Windows user? Existing projects and attempts will not switch automatically.`,'Save session')) {
      status.textContent='Not saved. Your selected file is unchanged.'; return;
    }
    await api('/api/settings/flow-cookie/save',{method:'POST',body:JSON.stringify(draft)});
    $('#flowCookieFile').value='';
    toast('Flow session saved securely. Test connection before use.');
    await showSettings();
  }));
  $('#testFlowCookie').addEventListener('click',()=>flowCookieAction('Checking Flow access. No video will be generated...',async status=>{
    const result = await api('/api/settings/flow-cookie/test',{method:'POST',body:JSON.stringify({account_id:$('#flowCookieAccount').value,project_url:$('#flowCookieProject').value.trim()})});
    status.textContent = result.message || result.reason_code || 'Check completed.';
    if (!result.live_verified) toast(status.textContent,true);
  }));
  $('#removeFlowCookie').addEventListener('click',()=>flowCookieAction('Review local session removal...',async status=>{
    const account=flowCookieAccounts.find(item=>item.account_id===$('#flowCookieAccount').value);
    if (!account) return;
    if (!await confirmFlowAction(`Remove saved Flow session "${account.account_id}" (revision ${account.revision}) from Story Auto? Pending recovery will need this session. This does not log out Google or stop work already running. Reimporting will create a different revision, never silently reuse an old attempt.`,'Remove saved session')) {
      status.textContent='Not removed. Your saved session is unchanged.'; return;
    }
    await api('/api/settings/flow-cookie/remove',{method:'POST',body:JSON.stringify({account_id:account.account_id,expected_revision:account.revision,confirm_remove:true})});
    toast('Saved session removed locally. Google sign-in is unchanged.');
    await showSettings();
  }));
  function dolaAccountDraft() {
    const text = $('#dolaAccountsInput').value.trim();
    if (text.startsWith('[')) {
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed) && parsed.some(item => item && typeof item === 'object' && Object.hasOwn(item, 'domain'))) {
          return {account_id: $('#dolaAccountName').value.trim(), cookie_export: parsed};
        }
      } catch (_) { /* The server returns a sanitized format error. */ }
    }
    return text;
  }
  async function previewDolaAccounts() {
    const accounts = dolaAccountDraft();
    if (!$('#dolaAccountsInput').value.trim()) { toast('Paste a Dola Cookie-Editor export or named cookie account.', true); $('#dolaAccountsInput').focus(); return null; }
    const result = await api('/api/settings/dola/preview',{method:'POST',body:JSON.stringify({accounts})});
    const target = $('#dolaPreview');
    if (target) target.textContent = `${result.incoming_count} account(s): ${result.new_count} new, ${result.updated_count} updated. Names: ${(result.account_ids || []).join(', ')}.`;
    return result;
  }
  function showDolaInputError(error) {
    const message = error?.payload?.failure_class === 'DOLA_ACCOUNT_INPUT_INVALID'
      ? error.payload.error : friendlyError(error).message;
    const target = $('#dolaPreview'); if (target) target.textContent = message;
    toast(message, true);
  }
  $('#previewDolaAccounts')?.addEventListener('click', async () => {
    try { await previewDolaAccounts(); } catch (error) { showDolaInputError(error); }
  });
  $('#saveDolaAccounts')?.addEventListener('click', async () => {
    try {
      const preview = await previewDolaAccounts(); if (!preview) return;
      if (!window.confirm(`Save ${preview.new_count} new and update ${preview.updated_count} Dola account(s)? Names: ${(preview.account_ids || []).join(', ')}`)) return;
      const result = await api('/api/settings/dola/save',{method:'POST',body:JSON.stringify({accounts:dolaAccountDraft()})});
      $('#dolaAccountsInput').value=''; const target=$('#dolaPreview'); if (target) target.textContent='';
      toast(`${result.new_count || 0} new and ${result.updated_count || 0} updated Dola account(s) saved.`); await showSettings();
    } catch (error) { showDolaInputError(error); }
  });
  document.querySelectorAll('[data-remove-dola-account]').forEach(button => button.addEventListener('click', async () => {
    const accountId=button.dataset.removeDolaAccount;
    if (!window.confirm(`Remove saved Dola account "${accountId}"? You can add it again with a fresh cookie.`)) return;
    try { await api('/api/settings/dola/remove',{method:'POST',body:JSON.stringify({account_id:accountId})}); toast(`Removed Dola account ${accountId}.`); await showSettings(); }
    catch (error) { toast(friendlyError(error).message, true); }
  }));
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
  return {
    id: ++state.nextDraftId, revision: 0, step: 1, source: 'STORY_CONTENT', content: '', info: null,
    voice: '', style: 'natural', mode: 'full_image', execution: 'FULL',
    importedAudio: null, importedSrt: null, sourceValidation: null, ambientStyle: 'quiet_verdict',
    fullImage: {image_duration_seconds:30, cadence:'SEMANTIC_ADAPTIVE', motion:'AUTO_CONTINUOUS_ZOOM', audio_visualizer:true},
    qcPolicy: 'AUTO_ACCEPT',
    flowConnection: null, seedance: null, elyum: null, pexels: null, openingProviderPolicy: 'AUTO', touched: {}, creating: false,
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
  draft.flowConnection = payload.flow_connection || null;
  draft.seedance = payload.seedance || null;
  draft.elyum = payload.elyum || null;
  draft.pexels = payload.pexels || null;
  if (!draft.touched.openingProviderPolicy) draft.openingProviderPolicy = String(payload.creation_defaults?.hybrid_visual?.opening_provider_policy || 'AUTO').toUpperCase();
  const defaults = payload.defaults || {};
  if (!draft.touched.voice && !draft.voice) draft.voice = defaults.voice_id || '';
  if (!draft.touched.mode) draft.mode = 'full_image';
  if (!draft.touched.ambientStyle) draft.ambientStyle = defaults.ambient_style || 'quiet_verdict';
  if (!draft.touched.qcPolicy) draft.qcPolicy = payload.creation_defaults?.qc_policy || 'AUTO_ACCEPT';
  if (!draft.touched.fullImage && payload.creation_defaults?.full_image) draft.fullImage = clone(payload.creation_defaults.full_image);
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
  const readiness = wizard.sourceValidation;
  if (!readiness) return `<p class="hint" id="sourceReadiness">${wizard.source === 'AUDIO_SRT' ? 'Choose narration audio and a matching SRT. Continue becomes available after both files are ready.' : 'Choose a readable narration file. Continue becomes available after it is ready.'}</p>`;
  const mark = component => component?.status === 'READY' ? '✓' : component?.status === 'BLOCKED' ? '✕' : '–';
  const audio = readiness.audio || {}, srt = readiness.srt || {}, timeline = readiness.timeline || {};
  const ready = readiness.status === 'READY';
  return `<section class="surface" id="sourceReadiness" aria-live="polite"><strong>${ready ? 'Ready to continue' : 'Input needs attention'}</strong><p>${mark(audio)} Audio ${audio.status === 'READY' ? 'ready' : 'needs attention'}<br><small>${esc(audio.message || '')}</small></p>${wizard.source === 'AUDIO_SRT' ? `<p>${mark(srt)} Subtitles ${srt.status === 'READY' ? 'ready' : 'need attention'}<br><small>${esc(srt.message || '')}</small></p><p>${mark(timeline)} Timing ${timeline.status === 'READY' ? 'matches' : 'needs attention'}<br><small>${esc(timeline.message || '')}</small></p><details class="disclosure"><summary>Details</summary><div class="technical">${esc(JSON.stringify(readiness,null,2))}</div></details>` : ''}</section>`;
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
  // Starting a different journey revokes any not-yet-executed Home intent,
  // even if the dialog closes before the old workspace response arrives.
  if (state.projectOpenToken && !state.snapshot) { state.view = 'home'; state.project = null; }
  state.projectOpenToken = null;
  if (!state.runToken) setBusy(false);
  const isNew = !state.wizard;
  if (isNew) state.wizard = freshDraft();
  const wizard=state.wizard;
  renderWizard();
  if (!$('#newVideoDialog').open) $('#newVideoDialog').showModal();
  focusWizardStep();
  // Show the source shell before probing local defaults/capabilities.  The
  // probe can inspect the local narrator inventory, so it must never delay the
  // first useful New Video frame.
  if (isNew) setTimeout(() => hydrateCreationDefaults(wizard), 0);
}

function wizardSteps() {
  const labels = ['Source','Input','Output & quality','Review'];
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
    const target = state.wizard.step === 1 ? $('#sourceStory') : state.wizard.step === 2 ? $('#contentInput') || $('#existingAudio') : state.wizard.step === 3 ? $('#fullImageDuration') || $('#formatChoice') : $('#wizardTitle');
    target?.focus();
  });
}

function renderWizard() {
  const wizard = state.wizard;
  $('#wizardSteps').innerHTML = wizardSteps(); showWizardError('');
  const title = wizard.step === 1 ? 'Choose your source' : wizard.step === 2 ? 'Add your input' : wizard.step === 3 ? 'Choose output and quality' : 'Review and create';
  $('#wizardTitle').textContent = title;
  if (wizard.step === 1 || wizard.step === 2) {
    const fields = wizard.source === 'STORY_CONTENT'
      ? `<div class="file-drop"><label class="field-label" for="contentFile">Choose an approved content package or content.md</label><input id="contentFile" type="file" accept=".md,.txt,text/markdown,text/plain"><p class="hint">The file stays on this computer and is read into the project when you create it.</p></div><div class="field" style="margin-top:18px"><label for="contentInput">Content</label><textarea id="contentInput" spellcheck="true" placeholder="# Story title\n\n## Narration\n\nPaste approved narration here.">${esc(wizard.content)}</textarea><small id="contentHelp">Story Auto checks for one non-empty Narration section.</small></div>`
      : wizard.source === 'EXISTING_AUDIO'
        ? `<div class="file-drop"><label class="field-label" for="existingAudio">Narration audio</label><input id="existingAudio" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/flac,audio/ogg,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"><p class="hint">${wizard.importedAudio ? `Selected: ${esc(wizard.importedAudio.filename)}.` : 'Choose a readable narration file.'} TTS will be skipped.</p></div><div class="field" style="margin-top:18px"><label for="contentInput">Canonical narration text</label><textarea id="contentInput" spellcheck="true" placeholder="# Narration source\n\n## Narration\n\nPaste the narration spoken in this audio.">${esc(wizard.content)}</textarea><small id="contentHelp">Needed to plan visuals truthfully when no SRT timing is supplied.</small></div>`
        : `<div class="file-drop"><label class="field-label" for="existingAudio">Narration audio</label><input id="existingAudio" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/flac,audio/ogg,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"><p class="hint">${wizard.importedAudio ? `Selected: ${esc(wizard.importedAudio.filename)}.` : 'Required.'}</p></div><div class="file-drop" style="margin-top:18px"><label class="field-label" for="existingSrt">Matching SRT timing</label><input id="existingSrt" type="file" accept=".srt,text/plain"><p class="hint">${wizard.importedSrt ? `Selected: ${esc(wizard.importedSrt.filename)}.` : 'Required.'} Its text becomes the canonical project narration; no content.md is required from you.</p></div>`;
    const choices = `<fieldset class="field"><legend>INPUT SOURCE</legend><div class="choice-grid"><label class="choice"><input id="sourceStory" type="radio" name="inputSource" value="STORY_CONTENT" ${wizard.source === 'STORY_CONTENT' ? 'checked' : ''}><strong>Create from Story / Content</strong><small>Provide narration or story text and Story Auto creates the narration.</small></label><label class="choice"><input type="radio" name="inputSource" value="EXISTING_AUDIO" ${wizard.source === 'EXISTING_AUDIO' ? 'checked' : ''}><strong>Create from Existing Audio</strong><small>Provide recorded narration and its matching text.</small></label><label class="choice"><input type="radio" name="inputSource" value="AUDIO_SRT" ${wizard.source === 'AUDIO_SRT' ? 'checked' : ''}><strong>Create from Audio + SRT</strong><small>Provide narration audio and matching subtitle timing.</small></label></div></fieldset>`;
    $('#wizardContent').innerHTML = wizard.step === 1 ? choices : `<p class="hint">Source: <strong>${esc(sourceLabel(wizard.source))}</strong></p><div style="margin-top:20px">${fields}${sourceStatusMarkup(wizard)}</div>`;
    document.querySelectorAll('input[name="inputSource"]').forEach(input => input.addEventListener('change', event => { wizard.source=event.target.value; wizard.execution=sourceExecution(wizard.source); wizard.sourceValidation=null; touchDraft(wizard,'source'); renderWizard(); focusWizardStep(); }));
    $('#contentInput')?.addEventListener('input', event => { wizard.content = event.target.value; touchDraft(wizard,'content'); });
    $('#contentFile')?.addEventListener('change', async event => { const file=event.target.files?.[0]; if (file) { const content=await file.text(); if (activeDraft(wizard)) { wizard.content=content; touchDraft(wizard,'content'); $('#contentInput').value=wizard.content; } } });
    $('#existingAudio')?.addEventListener('change', event => readBrowserImport(event,'importedAudio'));
    $('#existingSrt')?.addEventListener('change', event => readBrowserImport(event,'importedSrt'));
  } else if (wizard.step === 3) {
    const contextualStyle = wizard.mode === 'full_image'
        ? `<fieldset class="field contextual-field" id="fullImageSettings"><legend>FULL IMAGE</legend><fieldset class="field"><legend>Scene / Image duration</legend><div class="choice-grid">${[10,15,20,30,60].map(seconds => `<label class="choice"><input type="radio" name="fullImagePreset" value="${seconds}" ${Number(wizard.fullImage.image_duration_seconds) === seconds ? 'checked' : ''}><strong>${seconds} sec</strong></label>`).join('')}<label class="choice"><input type="radio" name="fullImagePreset" value="custom" ${[10,15,20,30,60].includes(Number(wizard.fullImage.image_duration_seconds)) ? '' : 'checked'}><strong>Custom</strong></label></div><div class="field" style="margin-top:12px" ${[10,15,20,30,60].includes(Number(wizard.fullImage.image_duration_seconds)) ? 'hidden' : ''}><label for="fullImageDuration">Custom seconds</label><input id="fullImageDuration" type="number" min="5" max="120" step="1" value="${esc(wizard.fullImage.image_duration_seconds)}"></div></fieldset><div class="settings-grid"><div class="field"><label for="fullImageCadence">Cadence</label><select id="fullImageCadence"><option value="SEMANTIC_ADAPTIVE" ${wizard.fullImage.cadence === 'SEMANTIC_ADAPTIVE' ? 'selected' : ''}>Semantic Adaptive</option><option value="FIXED" ${wizard.fullImage.cadence === 'FIXED' ? 'selected' : ''}>Fixed</option></select></div></div><div class="choice-grid"><label class="choice"><strong>Motion</strong><small>AUTO CONTINUOUS ZOOM</small></label><label class="choice"><input id="fullImageWaveform" type="checkbox" ${wizard.fullImage.audio_visualizer ? 'checked' : ''}><strong>Waveform: ${wizard.fullImage.audio_visualizer ? 'ON' : 'OFF'}</strong><small>Uses the final narration audio.</small></label></div></fieldset>`
        : `<fieldset class="field contextual-field"><legend>Visual tone</legend><div class="choice-grid"><label class="choice"><input type="radio" name="style" value="natural" ${wizard.style === 'natural' ? 'checked' : ''}><strong>Natural cinematic</strong><small>Restrained, story-first visuals with dependable defaults.</small></label><label class="choice"><input type="radio" name="style" value="documentary" ${wizard.style === 'documentary' ? 'checked' : ''}><strong>Quiet documentary</strong><small>Grounded pacing and observational visual language.</small></label></div></fieldset>`;
    const narratorHelp = installedVoices().length ? (wizard.voice ? 'Kokoro Local uses the installed narrator you select here.' : 'The saved default narrator is unavailable. Choose an installed narrator before continuing.') : 'No installed Kokoro narrators are available. Configure Kokoro in Settings before creating a video.';
    const hybridProviderContext = wizard.mode === 'hybrid_hook'
      ? `<section class="surface" style="margin-top:20px"><strong>HYBRID VISUAL PROVIDERS</strong><div class="field" style="margin-top:12px"><label for="hybridOpeningProviderPolicy">Opening provider policy</label><select id="hybridOpeningProviderPolicy"><option value="AUTO" ${wizard.openingProviderPolicy === 'AUTO' ? 'selected' : ''}>Auto - offer ready providers, never auto-spend</option><option value="BYTEPLUS" ${wizard.openingProviderPolicy === 'BYTEPLUS' ? 'selected' : ''}>BytePlus only</option><option value="ELYUM" ${wizard.openingProviderPolicy === 'ELYUM' ? 'selected' : ''}>Elyum only</option><option value="MANUAL" ${wizard.openingProviderPolicy === 'MANUAL' ? 'selected' : ''}>Manual only</option></select><small>BytePlus: ${wizard.seedance?.status === 'READY' ? 'ready' : 'not configured'} · Elyum: ${wizard.elyum?.configured ? 'configured' : 'not configured'}. Auto only controls which choices are offered; it never dispatches or spends by itself.</small></div><p class="hint">Body images - Google Flow. Stock video - ${wizard.pexels?.configured ? 'Pexels configured' : 'Pexels not configured; generated-image fallback will be used'}.</p></section>`
      : '';
    const sourceContext = wizard.source === 'STORY_CONTENT' ? `<div class="field" style="margin-top:20px"><label for="voiceChoice">Narrator voice</label><select id="voiceChoice" ${installedVoices().length ? '' : 'disabled'}>${voiceOptions(wizard.voice)}</select><small>${esc(narratorHelp)}</small></div>` : `<section class="surface" style="margin-top:20px"><strong>${esc(sourceLabel(wizard.source))}</strong><p class="hint">Narration audio: IMPORT · TTS: SKIP · Timing: ${wizard.source === 'AUDIO_SRT' ? 'SRT' : 'ALIGNMENT'}.</p></section>`;
    const qualityPolicy = wizard.mode === 'full_video_ai'
      ? `<fieldset class="field contextual-field"><legend>Quality review</legend><div class="choice-grid"><label class="choice"><input type="radio" name="qcPolicy" value="MANUAL_REVIEW" checked><strong>Manual</strong><small>Full Video pauses after each technically valid Seedance result. Automated video QC is not treated as accepted yet.</small></label><label class="choice" aria-disabled="true"><input type="radio" name="qcPolicy" value="AUTO_ACCEPT" disabled><strong>Automatic — not enabled yet</strong><small>Image-only automatic QC is not reused for video.</small></label></div></fieldset>`
      : `<fieldset class="field contextual-field"><legend>Quality review</legend><div class="choice-grid"><label class="choice"><input type="radio" name="qcPolicy" value="AUTO_ACCEPT" ${wizard.qcPolicy === 'AUTO_ACCEPT' ? 'checked' : ''}><strong>Automatic</strong><small>Story Auto checks quality and story fit, then continues when the visual passes.</small></label><label class="choice"><input type="radio" name="qcPolicy" value="MANUAL_REVIEW" ${wizard.qcPolicy === 'MANUAL_REVIEW' ? 'checked' : ''}><strong>Manual</strong><small>Pause for your review before rendering.</small></label></div></fieldset>`;
    $('#wizardContent').innerHTML = `<fieldset class="field"><legend>Format</legend><div class="choice-grid format-grid"><label class="choice"><input id="formatChoice" type="radio" name="format" value="full_image" ${wizard.mode === 'full_image' ? 'checked' : ''}><strong>FULL IMAGE</strong><small>Images only, AUTO CONTINUOUS ZOOM, and optional waveform.</small></label><label class="choice"><input type="radio" name="format" value="hybrid_hook" ${wizard.mode === 'hybrid_hook' ? 'checked' : ''}><strong>HYBRID VISUAL</strong><small>15-20s opening video, then images/effects with semantic stock-video slots. Opening clips can be created externally and imported into exact slots.</small></label><label class="choice"><input type="radio" name="format" value="full_video_ai" ${wizard.mode === 'full_video_ai' ? 'checked' : ''}><strong>FULL VIDEO</strong><small>Seedance 2.5 through the direct BytePlus async API. No browser session is required.</small></label></div></fieldset>${qualityPolicy}${contextualStyle}${hybridProviderContext}${sourceContext}`;
    document.querySelectorAll('input[name="format"]').forEach(input => input.addEventListener('change', event => { wizard.mode = event.target.value; if (wizard.mode === 'full_video_ai') wizard.qcPolicy='MANUAL_REVIEW'; touchDraft(wizard,'mode'); renderWizard(); document.querySelector(`input[name="format"][value="${wizard.mode}"]`)?.focus(); }));
    document.querySelectorAll('input[name="style"]').forEach(input => input.addEventListener('change', event => { wizard.style = event.target.value; touchDraft(wizard,'style'); }));
    document.querySelectorAll('input[name="ambientStyle"]').forEach(input => input.addEventListener('change', event => { wizard.ambientStyle = event.target.value; touchDraft(wizard,'ambientStyle'); }));
    document.querySelectorAll('input[name="qcPolicy"]').forEach(input => input.addEventListener('change', event => { wizard.qcPolicy = event.target.value; touchDraft(wizard,'qcPolicy'); }));
    $('#fullImageDuration')?.addEventListener('input', event => { wizard.fullImage.image_duration_seconds = Number(event.target.value); touchDraft(wizard,'fullImage'); });
    document.querySelectorAll('input[name="fullImagePreset"]').forEach(input => input.addEventListener('change', event => { if (event.target.value !== 'custom') wizard.fullImage.image_duration_seconds=Number(event.target.value); else if ([10,15,20,30,60].includes(Number(wizard.fullImage.image_duration_seconds))) wizard.fullImage.image_duration_seconds=25; touchDraft(wizard,'fullImage'); renderWizard(); }));
    $('#fullImageCadence')?.addEventListener('change', event => { wizard.fullImage.cadence = event.target.value; touchDraft(wizard,'fullImage'); });
    $('#fullImageWaveform')?.addEventListener('change', event => { wizard.fullImage.audio_visualizer = event.target.checked; touchDraft(wizard,'fullImage'); renderWizard(); });
    $('#voiceChoice')?.addEventListener('change', event => { wizard.voice = event.target.value; touchDraft(wizard,'voice'); });
    $('#hybridOpeningProviderPolicy')?.addEventListener('change', event => { wizard.openingProviderPolicy = event.target.value; touchDraft(wizard,'openingProviderPolicy'); });
  } else {
    const source = wizard.source;
    const visualRun = wizard.mode === 'full_image' ? 'Create images' : 'Create visuals';
    const providerReady = wizard.execution === 'RENDER_ONLY' || (wizard.mode === 'full_video_ai' ? wizard.seedance?.status === 'READY' : wizard.flowConnection?.status === 'CONNECTED');
    const providerLine = wizard.mode === 'hybrid_hook'
      ? `Opening policy: ${wizard.openingProviderPolicy} · Flow body images: ${wizard.flowConnection?.status === 'CONNECTED' ? 'ready' : 'reconnect if generation pauses'} · Pexels stock: ${wizard.pexels?.configured ? 'configured' : 'not configured — image fallback enabled'}`
      : providerReady ? (wizard.mode === 'full_video_ai' ? 'BytePlus Seedance API ready' : 'Ready')
        : (wizard.mode === 'full_video_ai' ? 'Needs BytePlus ModelArk API key in the Story Auto environment.' : 'Needs attention — you can reconnect Flow from the project.');
    $('#wizardContent').innerHTML = `<p class="hint">Check these choices before Story Auto creates the project.</p><dl class="review-summary"><div class="summary-row"><dt>Source</dt><dd>${esc(sourceLabel(source))}</dd><button class="change-step" data-change-step="1" type="button">Change</button></div><div class="summary-row"><dt>Expected duration</dt><dd>${source === 'STORY_CONTENT' ? esc(formatDuration(wizard.info?.estimated_duration_seconds)) : 'Known from your audio'}</dd><button class="change-step" data-change-step="2" type="button">Change</button></div><div class="summary-row"><dt>Output style</dt><dd>${esc(humanMode(wizard.mode))}</dd><button class="change-step" data-change-step="3" type="button">Change</button></div><div class="summary-row"><dt>Quality review</dt><dd>${wizard.qcPolicy === 'AUTO_ACCEPT' ? 'Automatic' : 'Manual'}</dd></div><div class="summary-row"><dt>Provider readiness</dt><dd>${providerLine}</dd></div>${wizard.mode === 'full_image' ? `<div class="summary-row"><dt>Scene pacing</dt><dd>${esc(wizard.fullImage.image_duration_seconds)} seconds · ${esc(wizard.fullImage.cadence === 'FIXED' ? 'Fixed' : 'Adaptive')} · Waveform ${wizard.fullImage.audio_visualizer ? 'On' : 'Off'}</dd><button class="change-step" data-change-step="3" type="button">Change</button></div>` : ''}</dl><section class="surface" style="margin-top:22px"><h3>Execution summary</h3><p class="hint">Audio — ${source === 'STORY_CONTENT' ? 'Create narration' : 'Use uploaded file'}<br>Timing — ${source === 'AUDIO_SRT' ? 'Use subtitle timing' : 'Prepare timing'}<br>Visuals — ${visualRun}<br>Quality — ${wizard.qcPolicy === 'AUTO_ACCEPT' ? 'Automatic' : 'Manual review'}<br>Final video — Create</p></section>`;
    document.querySelectorAll('[data-change-step]').forEach(button => button.addEventListener('click', () => { wizard.step = Number(button.dataset.changeStep); touchDraft(wizard,'step'); renderWizard(); focusWizardStep(); }));
  }
  const importBlocked = wizard.step === 2 && wizard.source !== 'STORY_CONTENT' && wizard.sourceValidation?.status !== 'READY';
  const nextDisabled = importBlocked || wizard.creating;
  const nextReason = importBlocked ? ' aria-describedby="sourceReadiness"' : '';
  $('#wizardActions').innerHTML = `<button class="button-quiet" id="cancelWizard" type="button">Cancel</button><div class="right">${wizard.step > 1 ? '<button id="wizardBack" type="button">Back</button>' : ''}<button class="button-primary" id="wizardNext" type="button" ${nextDisabled ? 'disabled' : ''}${nextReason}>${wizard.step === 4 ? 'Create video' : 'Continue'}</button></div>`;
  $('#cancelWizard').addEventListener('click', closeWizard);
  $('#wizardBack')?.addEventListener('click', () => { wizard.step -= 1; touchDraft(wizard,'step'); renderWizard(); focusWizardStep(); });
  $('#wizardNext').addEventListener('click', advanceWizard);
}

async function advanceWizard() {
  const wizard = state.wizard;
  if (!wizard) return;
  if (wizard.step === 1) {
    wizard.step = 2; touchDraft(wizard,'step'); renderWizard(); focusWizardStep();
    return;
  }
  if (wizard.step === 2) {
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
      try {
        const readiness=await validateSourceImports(wizard);
        if (!bindingIsCurrent(wizard,binding)) return;
        if (readiness?.status !== 'READY') { showWizardError(readiness?.message || 'Choose valid narration imports before continuing.',wizard.source === 'AUDIO_SRT' ? 'existingSrt' : 'existingAudio'); renderWizard(); return; }
      } catch (error) { if (!activeDraft(wizard)) return; showWizardError(friendlyError(error).message,wizard.source === 'AUDIO_SRT' ? 'existingSrt' : 'existingAudio'); return; }
    }
    if (!bindingIsCurrent(wizard,binding)) return;
    wizard.execution=sourceExecution(wizard.source); wizard.step = 3; touchDraft(wizard,'step'); renderWizard(); focusWizardStep();
    return;
  }
  if (wizard.step === 3) {
    if (!['full_image','hybrid_hook','full_video_ai'].includes(wizard.mode)) { showWizardError('Choose an available output format.','formatChoice'); return; }
    if (wizard.mode === 'full_video_ai' && wizard.seedance?.status !== 'READY') { showWizardError('Full Video needs a BytePlus ModelArk API key before the project can start.','formatChoice'); return; }
    if (wizard.mode === 'ambient_story' && !['quiet_verdict','hidden_mastery'].includes(wizard.ambientStyle)) { showWizardError('Choose an Ambient Story style.','ambientStyleField'); return; }
    if (wizard.mode === 'full_image' && (!Number.isFinite(Number(wizard.fullImage.image_duration_seconds)) || Number(wizard.fullImage.image_duration_seconds) < 5 || Number(wizard.fullImage.image_duration_seconds) > 120 || !['SEMANTIC_ADAPTIVE','FIXED'].includes(wizard.fullImage.cadence))) { showWizardError('Choose an image duration between 5 and 120 seconds and a cadence.','fullImageSettings'); return; }
    if (wizard.source === 'STORY_CONTENT' && !hasInstalledVoice(wizard.voice)) { showWizardError('Choose an installed narrator before continuing.','voiceChoice'); return; }
    wizard.step = 4; touchDraft(wizard,'step'); renderWizard(); focusWizardStep(); return;
  }
  if (wizard.creating) return;
  if (wizard.source !== 'STORY_CONTENT') {
    const readiness=await validateSourceImports(wizard);
    if (!activeDraft(wizard)) return;
    if (readiness?.status !== 'READY') { showWizardError(readiness?.message || 'Choose valid narration imports before creating a video.'); renderWizard(); return; }
  }
  const button = $('#wizardNext'); wizard.creating = true; button.disabled = true; button.textContent = 'Creating…';
  try {
    const settings = clone(state.creationDefaults?.creation_defaults || state.settings?.creation_defaults || {});
    const existingKokoro = settings.tts?.kokoro_local || {};
    wizard.execution=sourceExecution(wizard.source);
    if (wizard.execution === 'FULL') settings.tts = {provider:'kokoro_local',allow_cross_provider_fallback:false,kokoro_local:{...existingKokoro,voice_id:wizard.voice}};
    else delete settings.tts;
    settings.ui = {...settings.ui,production_style:wizard.style,input_source:wizard.source};
    settings.execution = {mode:wizard.execution};
    settings.qc_policy = wizard.qcPolicy;
    if (wizard.mode === 'ambient_story') settings.ambient_style = wizard.ambientStyle; else delete settings.ambient_style;
    if (wizard.mode === 'full_image') settings.full_image = {...wizard.fullImage, image_duration_seconds:Number(wizard.fullImage.image_duration_seconds), motion:'AUTO_CONTINUOUS_ZOOM'}; else delete settings.full_image;
    if (wizard.mode === 'hybrid_hook') settings.hybrid_visual = {...(settings.hybrid_visual || {}),cuj_enabled:true,audio_visualizer:true,opening_provider_policy:wizard.openingProviderPolicy}; else delete settings.hybrid_visual;
    const created = await api('/api/projects',{method:'POST',body:JSON.stringify({render_mode:wizard.mode,ambient_style:wizard.mode === 'ambient_story' ? wizard.ambientStyle : null,content:wizard.source === 'AUDIO_SRT' ? null : wizard.content,settings,imported_audio:wizard.execution === 'FULL' ? null : wizard.importedAudio,imported_srt:wizard.source === 'AUDIO_SRT' ? wizard.importedSrt : null})});
    state.projects = [created,...state.projects.filter(project => project.project_id !== created.project_id)];
    state.project = created.project_id; state.view = 'project'; setNav('home');
    state.snapshot = await api(`/api/projects/${encodeURIComponent(created.project_id)}/workspace`);
    renderProject(); focusMain();
    closeWizard(); toast('Video project created. Starting production…');
    void runAction('run_to_final','Starting production until it needs your decision…');
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
