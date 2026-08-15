const state = {
  view: 'home', projects: [], project: null, snapshot: null, settings: null,
  busy: false, busyLabel: '', error: null,
  wizard: { step: 1, content: '', info: null, voice: 'bm_george', style: 'natural', mode: 'hybrid_hook' }
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

function humanMode(mode) { return mode === 'full_video_ai' ? 'Full video animation' : 'Cinematic opening'; }
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
    <div class="card-top"><div><h3>${esc(project.title)}</h3><p class="meta">${esc(formatUpdated(project.updated_at))} · ${esc(humanMode(project.render_mode))}</p></div><span class="status-chip ${chipClass(project)}">${esc(project.user_status)}</span></div>
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
  const view = $('#view');
  view.innerHTML = '<div class="empty-library"><p>Loading your videos…</p></div>';
  try { await loadProjects(); } catch (error) {
    view.innerHTML = errorCard(friendlyError(error)); return;
  }
  const attention = state.projects.filter(project => project.attention?.length);
  const recent = state.projects.filter(project => !project.attention?.length);
  view.innerHTML = `<section class="hero">
    <div><p class="eyebrow">CONTENT TO FINISHED VIDEO</p><h2>Turn an approved story into a finished video.</h2><p>Add your content, choose a narrator, and let Story Auto guide production from voice to final review.</p><button class="button-primary" id="newVideoHero" type="button">＋ New video</button></div>
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
  catch (error) { setHeader('PROJECT','Could not open project'); $('#view').innerHTML = errorCard(friendlyError(error)); }
  finally { if (state.busy) setBusy(false); }
  if (moveFocus) focusMain();
}

function stageMarkup(snapshot) {
  const stages = ['Voice','Plan','Create visuals','Quality check','Render','Finish'];
  const current = Math.max(0, stages.indexOf(snapshot.current_stage));
  return `<ol class="stage-list" aria-label="Production stages">${stages.map((label,index) => `<li class="${snapshot.progress === 100 || index < current ? 'is-done' : index === current ? 'is-current' : ''}" ${index === current && snapshot.progress < 100 ? 'aria-current="step"' : ''}>${esc(label)}</li>`).join('')}</ol>`;
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
      <div class="project-facts"><div class="fact"><small>Narration</small><strong>${snapshot.word_count ? `${snapshot.word_count.toLocaleString()} words` : 'Needs content'}</strong></div><div class="fact"><small>Duration</small><strong>${esc(formatDuration(snapshot.duration_seconds))}</strong></div><div class="fact"><small>Style</small><strong>${esc(humanMode(snapshot.render_mode))}</strong></div></div>
      ${stageMarkup(snapshot)}
    </div>
    <div class="progress-panel"><div class="progress-value"><span>Overall progress</span><strong>${Number(snapshot.progress)}%</strong></div><div class="progress-track" role="progressbar" aria-label="Overall production progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(snapshot.progress)}"><span style="width:${Number(snapshot.progress)}%"></span></div><p>${esc(currentActivity)}</p></div>
  </section>
  ${state.error ? errorCard(state.error) : ''}
  ${attention ? `<section class="attention-card" aria-labelledby="attentionTitle"><div><h2 id="attentionTitle">${esc(attention.title)}</h2><p>${esc(attention.message)}</p><p class="reassurance">Your completed work is saved.</p></div><button class="button-primary" data-project-action="${esc(attention.action_id)}" type="button">${esc(attention.action)}</button><details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(attention.code)}</div></details></section>` : `<section class="surface next-action"><div><h2>${esc(snapshot.primary_action.action)}</h2><p>${snapshot.work_saved ? 'Completed stages are saved, so Resume continues from the next unfinished step.' : esc(snapshot.current_activity)}</p>${state.busy ? '<p class="hint">This may take several minutes. You can keep this window open.</p>' : ''}</div><button class="button-primary" data-project-action="${esc(snapshot.primary_action.action_id)}" type="button" ${state.busy ? 'disabled aria-describedby="busyReason"' : ''}>${state.busy ? 'Working…' : esc(snapshot.primary_action.action)}</button></section>`}
  <section class="surface"><div class="surface-head"><div><h2>Project overview</h2><p>Review the result when it is ready, or open technical detail when you need it.</p></div><div class="button-row"><button id="reviewProject" type="button">Review</button>${snapshot.current_stage === 'Create visuals' && !snapshot.final_path ? '<button id="pauseProject" type="button">Pause safely</button>' : ''}</div></div>
    <details class="disclosure" id="projectDetails"><summary>Show details</summary><div id="technicalContent" class="technical">Technical details load only when opened.</div></details>
  </section>`;
  document.querySelectorAll('[data-project-action]').forEach(button => button.addEventListener('click', () => handleProjectAction(button.dataset.projectAction)));
  $('#reviewProject')?.addEventListener('click', showReview);
  $('#pauseProject')?.addEventListener('click', () => runAction('pause','Pausing safely…'));
  bindDiagnosticsDisclosure();
}

function renderComplete(snapshot) {
  $('#view').innerHTML = `<section class="success-banner"><p class="eyebrow">VIDEO COMPLETE</p><h2>Your final video is ready.</h2><p>Story Auto finished the production and kept the project files available for review.</p></section>
  <section class="surface review-layout"><div>${snapshot.final_path ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(snapshot.project_id,snapshot.final_path)}" aria-label="Final video preview"></video>` : '<div class="video-frame"></div>'}</div>
    <aside class="review-sidebar"><span class="status-chip success">Complete</span><h3>${esc(snapshot.title)}</h3><p>${esc(formatDuration(snapshot.duration_seconds))} · ${esc(humanMode(snapshot.render_mode))}</p><p>Publishing package: <strong>${snapshot.publishing_status === 'READY' ? 'Ready' : 'Not prepared'}</strong></p><div class="button-row"><a class="button button-primary" href="${assetUrl(snapshot.project_id,snapshot.final_path)}" target="_blank" rel="noopener">Open final video</a><button id="openFolder" type="button">Open folder</button></div></aside>
  </section>
  <section class="surface next-action"><div><h2>Review or start another</h2><p>Inspect quality checks and publishing copy, or begin a new video.</p></div><div class="button-row"><button id="reviewComplete" type="button">Review</button><button id="createAnother" type="button">Create another video</button></div></section>
  <section class="surface"><details class="disclosure" id="projectDetails"><summary>Show details</summary><div id="technicalContent" class="technical">Technical details load only when opened.</div></details></section>`;
  $('#openFolder').addEventListener('click', () => runAction('open_output','Opening the output folder…'));
  $('#reviewComplete').addEventListener('click', showReview);
  $('#createAnother').addEventListener('click', openWizard);
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
  if (action === 'review_visuals' || action === 'review_project' || action === 'open_final') return showReview();
  if (action === 'process') return runAction('process','Creating voice and planning your story…');
  if (action === 'resume_generation') return runAction('resume_generation','Creating visuals. Completed work remains saved…');
  if (action === 'render') return runAction('render','Rendering the final video…');
  if (action === 'open_flow_sign_in') return runAction('open_flow_sign_in','Opening the Story Auto Flow sign-in window…');
}

async function runAction(action, label) {
  if (!state.project || state.busy) return;
  setBusy(true,label); state.error = null; renderProject();
  try {
    await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action})});
    state.snapshot = await api(`/api/projects/${encodeURIComponent(state.project)}/snapshot`);
    toast(action === 'pause' ? 'Production will pause at the next safe point.' : action === 'open_flow_sign_in' ? 'Flow sign-in opened.' : 'Project updated.');
  } catch (error) { state.error = friendlyError(error); toast(state.error.title,true); }
  finally { setBusy(false); renderProject(); }
}

function friendlyError(error) {
  const code = error?.payload?.failure_class || 'UNKNOWN_ERROR';
  const raw = error?.payload?.error || error?.message || code;
  const known = {
    FLOW_AUTH_REQUIRED: ['Google sign-in required','Sign in to Google Flow, then return here and choose Try again.','open_flow_sign_in','Open Flow sign-in'],
    TTS_PROVIDER_CREDITS_REQUIRED: ["Voice generation can't continue",'The selected paid voice provider does not have enough credits. Choose another voice or update the provider account.','settings','Open settings'],
    CREDENTIAL_MISSING: ['AI quality is not configured','Add the provider credential in the secure Story Auto configuration, then try again.','settings','Open settings'],
    GEMINI_CREDENTIAL_MISSING: ['AI quality is not configured','Add a Gemini credential in the secure Story Auto configuration, then try again.','settings','Open settings'],
    KOKORO_RUNTIME_NOT_FOUND: ['Local voice is not ready','Set the Kokoro installation location in Advanced settings, or choose an available narrator.','settings','Open settings'],
  };
  const match = known[code] || (code.includes('CREDIT') ? known.TTS_PROVIDER_CREDITS_REQUIRED : null);
  return { code, raw, title: match?.[0] || "Story Auto couldn't continue", message: match?.[1] || 'Review the project details and try again. Your completed work is safe.', action_id: match?.[2] || 'retry', action: match?.[3] || 'Try again' };
}

function errorCard(error) {
  return `<section class="attention-card" role="alert"><div><h2>${esc(error.title)}</h2><p>${esc(error.message)}</p><p class="reassurance">Your completed work is saved.</p></div><details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(error.code)}\n${esc(error.raw)}</div></details></section>`;
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

function qcReport() {
  const keys = ['SKIN_REALISM','LIGHTING_NATURALISM','MATERIAL_REALISM','COMPOSITION_NATURALISM','AI_POLISH','CONTINUITY','TECHNICAL_VALIDITY'];
  return {results:Object.fromEntries(keys.map(key => [key,'PASS'])),visible_provider_watermark:false,reviewer:'local_operator',notes:'Approved in Story Auto review'};
}

async function showReview() {
  setBusy(true,'Opening review…');
  try {
    const [review, media] = await Promise.all([api(`/api/projects/${encodeURIComponent(state.project)}/review`),api(`/api/projects/${encodeURIComponent(state.project)}/media`)]);
    setHeader('REVIEW',review.title,'<button class="button-quiet" id="backProject" type="button">← Project</button>');
    const byId = new Map([...media.references,...media.shots].map(item => [item.request.request_id,item]));
    const issues = review.issues.map(issue => {
      const item = byId.get(issue.request_id) || {}; const selected = item.selected_asset;
      const preview = selected ? (issue.media_type === 'VIDEO' ? `<video class="video-frame" controls preload="metadata" src="${assetUrl(state.project,selected.path)}"></video>` : `<img class="video-frame" src="${assetUrl(state.project,selected.path)}" alt="Generated scene ${issue.scene}">`) : '';
      return `<article class="issue">${preview}<h3>Scene ${issue.scene}</h3><p>${esc(issue.message)}</p><div class="button-row">${issue.status === 'QC_PENDING' ? `<button class="button-primary" data-approve="${esc(issue.request_id)}" type="button">Approve scene</button>` : ''}<button data-regenerate="${esc(issue.request_id)}" type="button">Regenerate</button></div><details class="disclosure"><summary>Technical details</summary><div class="technical">${esc(issue.status)}\n${esc(issue.request_id)}</div></details></article>`;
    }).join('');
    const publishing = review.publishing || {};
    $('#view').innerHTML = `<section class="surface"><div class="surface-head"><div><h2>Quality review</h2><p>${review.final_path ? `Final duration ${esc(formatDuration(review.duration_seconds))}.` : 'Review flagged scenes before production continues.'}</p></div>${review.final_path ? `<a class="button button-primary" href="${assetUrl(state.project,review.final_path)}" target="_blank" rel="noopener">Open final video</a>` : ''}</div>${qualityCards(review.quality)}</section>
      ${review.final_path ? `<section class="surface review-layout"><video class="video-frame" controls preload="metadata" src="${assetUrl(state.project,review.final_path)}" aria-label="Final video review"></video><aside class="review-sidebar"><h3>Publishing package</h3><p><strong>${esc(publishing.selected_title || review.title)}</strong></p><p class="publishing-copy">${esc(publishing.description || 'Publishing copy has not been prepared yet.')}</p>${publishing.description ? '<button id="copyPublishing" type="button">Copy title & description</button>' : ''}</aside></section>` : ''}
      <section class="surface"><div class="surface-head"><div><h2>Flagged scenes</h2><p>${review.issues.length ? `${review.issues.length} scene${review.issues.length === 1 ? '' : 's'} need a decision.` : 'No remaining quality issues were found.'}</p></div></div><div class="issue-list">${issues || '<div class="empty-library"><strong>Quality checks are clear.</strong><p>No scene needs your attention.</p></div>'}</div></section>`;
    $('#backProject').addEventListener('click', () => openProject(state.project));
    $('#copyPublishing')?.addEventListener('click', async () => { await navigator.clipboard.writeText(`${publishing.selected_title || review.title}\n\n${publishing.description}`); toast('Title and description copied.'); });
    document.querySelectorAll('[data-approve]').forEach(button => button.addEventListener('click', async () => { await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'approve_asset',request_id:button.dataset.approve,report:qcReport()})}); toast('Scene approved.'); await showReview(); }));
    document.querySelectorAll('[data-regenerate]').forEach(button => button.addEventListener('click', async () => { await api(`/api/projects/${encodeURIComponent(state.project)}/actions`,{method:'POST',body:JSON.stringify({action:'regenerate',request_id:button.dataset.regenerate})}); toast('Scene queued for regeneration.'); await openProject(state.project); }));
  } catch (error) { $('#view').innerHTML = errorCard(friendlyError(error)); }
  finally { setBusy(false); }
  focusMain();
}

function savedDefaults() {
  try { return JSON.parse(localStorage.getItem('storyAutoDefaults') || '{}'); } catch (_) { return {}; }
}

async function showSettings() {
  state.view = 'settings'; state.project = null; state.snapshot = null; state.error = null;
  setNav('settings'); setHeader('APPLICATION','Settings');
  $('#view').innerHTML = '<div class="empty-library"><p>Loading settings…</p></div>';
  try { state.settings = await api('/api/settings'); } catch (error) { $('#view').innerHTML = errorCard(friendlyError(error)); return; }
  const saved = savedDefaults(); const defaults = {...state.settings.defaults,...saved};
  const providerRows = state.settings.providers.map(provider => `<div class="provider-row"><div><strong>${esc(provider.name)}</strong><small>${esc(provider.detail)}</small></div><span class="provider-state ${provider.status !== 'Ready' ? 'attention' : ''}">${esc(provider.status)}</span></div>`).join('');
  const projectOptions = state.projects.map(project => `<option value="${esc(project.project_id)}">${esc(project.title)}</option>`).join('');
  $('#view').innerHTML = `<div class="settings-layout">
    <section class="settings-section"><h2>General</h2><p>Defaults are applied to new videos and saved only in this local browser.</p><div class="settings-grid"><div class="field"><label for="defaultMode">Default production style</label><select id="defaultMode"><option value="hybrid_hook" ${defaults.render_mode === 'hybrid_hook' ? 'selected' : ''}>Cinematic opening</option><option value="full_video_ai" ${defaults.render_mode === 'full_video_ai' ? 'selected' : ''}>Full video animation</option></select></div><div class="field"><label for="defaultVoice">Default narrator</label><select id="defaultVoice"><option value="bm_george" ${defaults.voice_id === 'bm_george' ? 'selected' : ''}>George — Natural male narrator</option><option value="am_michael" ${defaults.voice_id === 'am_michael' ? 'selected' : ''}>Michael — Clear male narrator</option><option value="af_heart" ${defaults.voice_id === 'af_heart' ? 'selected' : ''}>Heart — Warm female narrator</option></select></div></div><div class="button-row" style="margin-top:18px"><button class="button-primary" id="saveDefaults" type="button">Save defaults</button></div></section>
    <section class="settings-section"><h2>Provider health</h2><p>Concise readiness based on this workspace's current configuration and project state.</p><div class="provider-list">${providerRows}</div></section>
    <section class="settings-section"><h2>Storage</h2><p>Story Auto keeps projects and generated media in its isolated local workspace.</p><dl class="summary-list"><div class="summary-row"><dt>Project location</dt><dd>${esc(state.settings.storage.project_location)}</dd></div><div class="summary-row"><dt>Free space</dt><dd>${state.settings.storage.free_gb} GB</dd></div></dl></section>
    <section class="settings-section"><h2>Advanced</h2><p>Technical configuration and diagnostics for troubleshooting.</p><details class="disclosure"><summary>Provider details</summary><dl class="summary-list"><div class="summary-row"><dt>Voice provider</dt><dd>${esc(state.settings.advanced.tts_provider)}</dd></div><div class="summary-row"><dt>Gemini model</dt><dd>${esc(state.settings.advanced.gemini_model)}</dd></div><div class="summary-row"><dt>Flow project</dt><dd>${esc(state.settings.advanced.flow_project)}</dd></div><div class="summary-row"><dt>Runtime root</dt><dd>${esc(state.settings.advanced.runtime_root)}</dd></div></dl></details>
      <details class="disclosure"><summary>Diagnostics</summary><div class="field"><label for="diagnosticProject">Project</label><select id="diagnosticProject">${projectOptions || '<option value="">No projects available</option>'}</select><small>Diagnostics may include internal IDs, exact paths, manifests, provider attempts, and raw status codes.</small></div><button id="openDiagnostics" type="button" style="margin-top:14px" ${projectOptions ? '' : 'disabled'}>Open diagnostics</button></details>
    </section>
  </div>`;
  $('#saveDefaults').addEventListener('click', () => { localStorage.setItem('storyAutoDefaults',JSON.stringify({render_mode:$('#defaultMode').value,voice_id:$('#defaultVoice').value})); toast('Defaults saved.'); });
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
  } catch (error) { $('#view').innerHTML = errorCard(friendlyError(error)); }
  $('#backSettings').addEventListener('click', showSettings);
  focusMain();
}

async function ensureSettings() { if (!state.settings) state.settings = await api('/api/settings'); }

async function openWizard() {
  try { await ensureSettings(); } catch (error) { toast(friendlyError(error).message,true); return; }
  const saved = savedDefaults();
  state.wizard = {step:1,content:'',info:null,voice:saved.voice_id || state.settings.defaults.voice_id || 'bm_george',style:'natural',mode:saved.render_mode || state.settings.defaults.render_mode || 'hybrid_hook'};
  renderWizard();
  $('#newVideoDialog').showModal();
  requestAnimationFrame(() => $('#contentInput')?.focus());
}

function wizardSteps() {
  const labels = ['Content','Style & Voice','Review & Create'];
  return labels.map((label,index) => `<li class="${index + 1 < state.wizard.step ? 'is-done' : index + 1 === state.wizard.step ? 'is-current' : ''}" ${index + 1 === state.wizard.step ? 'aria-current="step"' : ''}>${index + 1}. ${label}</li>`).join('');
}

function showWizardError(message) {
  const error = $('#wizardError');
  error.textContent = message; error.hidden = !message;
}

function renderWizard() {
  const wizard = state.wizard;
  $('#wizardSteps').innerHTML = wizardSteps(); showWizardError('');
  const title = wizard.step === 1 ? 'Add your content' : wizard.step === 2 ? 'Choose style and voice' : 'Review and create';
  $('#wizardTitle').textContent = title;
  if (wizard.step === 1) {
    $('#wizardContent').innerHTML = `<div class="file-drop"><label class="field-label" for="contentFile">Choose an approved content package or content.md</label><input id="contentFile" type="file" accept=".md,.txt,text/markdown,text/plain"><p class="hint">The file stays on this computer and is read into the project when you create it.</p></div><div class="field" style="margin-top:18px"><label for="contentInput">Content</label><textarea id="contentInput" spellcheck="true" placeholder="# Story title\n\n## Narration\n\nPaste approved narration here.">${esc(wizard.content)}</textarea><small>Story Auto checks for one non-empty Narration section.</small></div>`;
    $('#contentInput').addEventListener('input', event => wizard.content = event.target.value);
    $('#contentFile').addEventListener('change', async event => { const file = event.target.files?.[0]; if (file) { wizard.content = await file.text(); $('#contentInput').value = wizard.content; } });
  } else if (wizard.step === 2) {
    $('#wizardContent').innerHTML = `<div class="field"><span class="field-label">Production style</span><div class="choice-grid"><label class="choice"><input type="radio" name="style" value="natural" ${wizard.style === 'natural' ? 'checked' : ''}><strong>Natural cinematic</strong><small>Restrained, story-first visuals with dependable defaults.</small></label><label class="choice"><input type="radio" name="style" value="documentary" ${wizard.style === 'documentary' ? 'checked' : ''}><strong>Quiet documentary</strong><small>Grounded pacing and observational visual language.</small></label></div></div><div class="field" style="margin-top:20px"><label for="voiceChoice">Narrator voice</label><select id="voiceChoice"><option value="bm_george" ${wizard.voice === 'bm_george' ? 'selected' : ''}>George — Natural male narrator</option><option value="am_michael" ${wizard.voice === 'am_michael' ? 'selected' : ''}>Michael — Clear male narrator</option><option value="af_heart" ${wizard.voice === 'af_heart' ? 'selected' : ''}>Heart — Warm female narrator</option></select><small>Kokoro Local is the default free Stable provider. Provider detail remains available in Settings.</small></div><details class="disclosure"><summary>Advanced options</summary><div class="field"><label for="renderModeChoice">Production mode</label><select id="renderModeChoice"><option value="hybrid_hook" ${wizard.mode === 'hybrid_hook' ? 'selected' : ''}>Cinematic opening — video opening with image-led story body</option><option value="full_video_ai" ${wizard.mode === 'full_video_ai' ? 'selected' : ''}>Full video animation — video for every final scene</option></select></div></details>`;
    document.querySelectorAll('input[name="style"]').forEach(input => input.addEventListener('change', event => wizard.style = event.target.value));
    $('#voiceChoice').addEventListener('change', event => wizard.voice = event.target.value);
    $('#renderModeChoice').addEventListener('change', event => wizard.mode = event.target.value);
  } else {
    const voiceNames = {bm_george:'George — Natural male narrator',am_michael:'Michael — Clear male narrator',af_heart:'Heart — Warm female narrator'};
    $('#wizardContent').innerHTML = `<p class="hint">Check these choices before Story Auto creates the project.</p><dl class="review-summary"><div class="summary-row"><dt>Story</dt><dd>${esc(wizard.info.title)}</dd><button class="change-step" data-change-step="1" type="button">Change<span class="sr-only"> content</span></button></div><div class="summary-row"><dt>Narration</dt><dd>${wizard.info.word_count.toLocaleString()} words · about ${esc(formatDuration(wizard.info.estimated_duration_seconds))}</dd><span></span></div><div class="summary-row"><dt>Narrator</dt><dd>${esc(voiceNames[wizard.voice])}</dd><button class="change-step" data-change-step="2" type="button">Change<span class="sr-only"> narrator</span></button></div><div class="summary-row"><dt>Style</dt><dd>${wizard.style === 'documentary' ? 'Quiet documentary' : 'Natural cinematic'}</dd><button class="change-step" data-change-step="2" type="button">Change<span class="sr-only"> style</span></button></div><div class="summary-row"><dt>Production</dt><dd>${esc(humanMode(wizard.mode))}</dd><button class="change-step" data-change-step="2" type="button">Change<span class="sr-only"> production mode</span></button></div></dl><div class="surface" style="margin-top:22px"><strong>What happens next</strong><p class="hint">The project opens ready to start. Production moves through voice, planning, visuals, quality checks, and the final render while saving completed work.</p></div>`;
    document.querySelectorAll('[data-change-step]').forEach(button => button.addEventListener('click', () => { wizard.step = Number(button.dataset.changeStep); renderWizard(); }));
  }
  $('#wizardActions').innerHTML = `<button class="button-quiet" id="cancelWizard" type="button">Cancel</button><div class="right">${wizard.step > 1 ? '<button id="wizardBack" type="button">Back</button>' : ''}<button class="button-primary" id="wizardNext" type="button">${wizard.step === 3 ? 'Create video' : 'Continue'}</button></div>`;
  $('#cancelWizard').addEventListener('click', closeWizard);
  $('#wizardBack')?.addEventListener('click', () => { wizard.step -= 1; renderWizard(); });
  $('#wizardNext').addEventListener('click', advanceWizard);
}

async function advanceWizard() {
  const wizard = state.wizard;
  if (wizard.step === 1) {
    wizard.content = $('#contentInput').value;
    try { wizard.info = await api('/api/validate-content',{method:'POST',body:JSON.stringify({content:wizard.content})}); wizard.step = 2; renderWizard(); requestAnimationFrame(() => $('#voiceChoice').focus()); }
    catch (_) { showWizardError('Add exactly one non-empty Narration section before continuing.'); $('#contentInput').focus(); }
    return;
  }
  if (wizard.step === 2) { wizard.step = 3; renderWizard(); return; }
  const button = $('#wizardNext'); button.disabled = true; button.textContent = 'Creating…';
  try {
    const settings = clone(state.settings.creation_defaults || {});
    const existingKokoro = settings.tts?.kokoro_local || {};
    settings.tts = {provider:'kokoro_local',allow_cross_provider_fallback:false,kokoro_local:{...existingKokoro,voice_id:wizard.voice}};
    settings.ui = {production_style:wizard.style};
    const created = await api('/api/projects',{method:'POST',body:JSON.stringify({render_mode:wizard.mode,content:wizard.content,settings})});
    closeWizard(); toast('Video project created.'); await loadProjects(); state.project = created.project_id; state.snapshot = created; state.view = 'project'; setNav('home'); renderProject(); focusMain();
  } catch (error) { showWizardError(friendlyError(error).message); button.disabled = false; button.textContent = 'Create video'; }
}

function closeWizard() { const dialog = $('#newVideoDialog'); if (dialog.open) dialog.close(); }

$('#closeWizard').addEventListener('click', closeWizard);
$('#newVideoDialog').addEventListener('cancel', event => { event.preventDefault(); closeWizard(); });
$('#homeNav').addEventListener('click', () => showHome(true));
$('#settingsNav').addEventListener('click', async () => { if (!state.projects.length) { try { await loadProjects(); } catch (_) {} } await showSettings(); });

window.addEventListener('unhandledrejection', event => { event.preventDefault(); toast(friendlyError(event.reason).message,true); });
showHome().catch(error => { $('#view').innerHTML = errorCard(friendlyError(error)); });
