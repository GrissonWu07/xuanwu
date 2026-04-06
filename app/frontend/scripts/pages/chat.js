/**
 * chat.js - Chat Page Module
 */

import { initSession, getSessionKey, setSessionKey } from '../session-manager.js'
import { initChat, activateSession, abortCurrentStream, getCurrentAgentInfo } from '../chat-ui.js'
import {
  listSessions,
  deleteSession,
  listSessionAttachments,
  uploadSessionAttachment,
  listSessionSubagents,
  createSessionSubagentStatusStream,
  killSessionSubagent,
  steerSessionSubagent,
  retrySessionSubagent
} from '../api-client.js'
import { t } from '../i18n.js'
import { updateHeaderTitleText } from '../components/header.js'

let chatElement = null
let mounted = false
let currentSessionKey = null
let sessionsCache = []
let searchQuery = ''
let pageContainer = null
let currentAgentName = 'XuanWu'
let attachmentsCache = { uploads: [], artifacts: [] }
let subagentsCache = {
  runtime_available: false,
  total: 0,
  active_batch_id: '',
  queue_depth: 0,
  active: [],
  recent: []
}
let subagentConflictNotice = null
let subagentLoading = false
let subagentEventSource = null
let subagentReconnectTimer = null
let subagentRefreshTimer = null
let subagentLastRefreshAt = 0
const SUBAGENT_REFRESH_COOLDOWN_MS = 350
const SUBAGENT_STREAM_RECONNECT_MS = 1500
const SUBAGENT_CURSOR_PREFIX = 'xuanwu.subagent.cursor.'

export async function mount(container) {
  pageContainer = container

  container.innerHTML = `
    <div class="chat-page-shell">
      <div class="chat-canvas-shell">
        <div id="chat-empty-state" class="chat-empty-state hidden">
          <div class="chat-empty-inner">
            <h1 class="chat-empty-title"></h1>
            <p class="chat-empty-copy"></p>
          </div>
        </div>
        <div class="chat-canvas-frame">
          <deep-chat
            id="chat"
            style="width: 100%; height: 100%; display: flex; flex-direction: column;"
            textMarkdown="true">
          </deep-chat>
        </div>
        <div id="chat-attachment-strip" class="chat-attachment-strip">
          <div class="chat-attachment-bar">
            <button id="chat-attachment-upload-btn" class="chat-attachment-upload-btn" type="button">Attach</button>
            <input id="chat-attachment-input" type="file" hidden />
            <div id="chat-attachment-content" class="chat-attachment-content"></div>
          </div>
        </div>
        <div id="chat-subagent-strip" class="chat-subagent-strip">
          <div id="chat-subagent-content" class="chat-subagent-content"></div>
        </div>
      </div>
      <div id="confirmDialog" class="confirm-dialog hidden">
        <div class="confirm-content">
          <h3>${escapeHtml(t('dialog.confirmTitle'))}</h3>
          <p id="confirmMessage"></p>
          <div class="confirm-buttons">
            <button class="btn-cancel" type="button">${escapeHtml(t('dialog.cancel'))}</button>
            <button class="btn-confirm" type="button">${escapeHtml(t('dialog.confirm'))}</button>
          </div>
        </div>
      </div>
    </div>
  `

  try {
    await initSession()
    currentSessionKey = getSessionKey()
  } catch (error) {
    console.error('[ChatPage] Failed to initialize session:', error)
    container.innerHTML = '<div class="error-message">Failed to initialize session.</div>'
    return
  }

  chatElement = container.querySelector('#chat')
  await initChat(chatElement, {
    onConversationStateChange: handleConversationStateChange,
    onUserTurnStarted: handleUserTurnStarted,
    onRunCompleted: handleRunCompleted,
    onToolEvent: handleToolEvent
  })

  currentAgentName = getCurrentAgentInfo()?.name || currentAgentName
  await loadSessions()
  await loadAttachments()
  await loadSubagents()
  mounted = true
  startSubagentStatusStream()
  bindDialogEvents(container)
  bindAttachmentEvents(container)
}

export async function unmount() {
  abortCurrentStream()
  const sidebarContent = document.getElementById('sidebar-dynamic-content')
  if (sidebarContent) sidebarContent.innerHTML = ''
  pageContainer = null
  chatElement = null
  currentSessionKey = null
  sessionsCache = []
  attachmentsCache = { uploads: [], artifacts: [] }
  subagentsCache = {
    runtime_available: false,
    total: 0,
    active_batch_id: '',
    queue_depth: 0,
    active: [],
    recent: []
  }
  subagentConflictNotice = null
  stopSubagentStatusStream()
  searchQuery = ''
  mounted = false
}

async function loadSessions() {
  const sidebarContent = document.getElementById('sidebar-dynamic-content')
  if (!sidebarContent) return

  try {
    sessionsCache = await listSessions()
  } catch (error) {
    console.error('[ChatPage] Failed to load sessions:', error)
    sessionsCache = []
  }

  ensureActiveSessionEntry()
  renderSidebarContent(sidebarContent)
  syncHeaderTitle()
}

async function loadAttachments() {
  if (!currentSessionKey || !pageContainer) {
    attachmentsCache = { uploads: [], artifacts: [] }
    renderAttachmentStrip()
    return
  }

  try {
    attachmentsCache = await listSessionAttachments(currentSessionKey)
  } catch (error) {
    console.error('[ChatPage] Failed to load attachments:', error)
    attachmentsCache = { uploads: [], artifacts: [] }
  }
  renderAttachmentStrip()
}

async function loadSubagents() {
  if (!currentSessionKey || !pageContainer) {
    subagentsCache = {
      runtime_available: false,
      total: 0,
      active_batch_id: '',
      queue_depth: 0,
      active: [],
      recent: []
    }
    renderSubagentStrip()
    return
  }
  if (subagentLoading) return
  subagentLoading = true
  try {
    const payload = await listSessionSubagents(currentSessionKey)
    subagentsCache = {
      runtime_available: !!payload?.runtime_available,
      total: Number(payload?.total || 0),
      active_batch_id: String(payload?.active_batch_id || ''),
      queue_depth: Number(payload?.queue_depth || 0),
      active: Array.isArray(payload?.active) ? payload.active : [],
      recent: Array.isArray(payload?.recent) ? payload.recent : []
    }
    subagentConflictNotice = deriveConflictNoticeFromCache()
  } catch (error) {
    console.error('[ChatPage] Failed to load subagents:', error)
    subagentsCache = {
      runtime_available: false,
      total: 0,
      active_batch_id: '',
      queue_depth: 0,
      active: [],
      recent: []
    }
    subagentConflictNotice = null
  } finally {
    subagentLoading = false
    renderSubagentStrip()
  }
}

function getSubagentCursorStorageKey(sessionKey) {
  return `${SUBAGENT_CURSOR_PREFIX}${sessionKey || ''}`
}

function loadSubagentCursor(sessionKey) {
  if (!sessionKey || typeof sessionStorage === 'undefined') return ''
  try {
    return String(sessionStorage.getItem(getSubagentCursorStorageKey(sessionKey)) || '')
  } catch (_error) {
    return ''
  }
}

function persistSubagentCursor(sessionKey, cursor) {
  if (!sessionKey || !cursor || typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(getSubagentCursorStorageKey(sessionKey), String(cursor))
  } catch (_error) {
    // ignore storage failures
  }
}

function scheduleSubagentRefresh() {
  if (!mounted || !currentSessionKey || subagentRefreshTimer) return
  const elapsed = Date.now() - subagentLastRefreshAt
  const delay = Math.max(0, SUBAGENT_REFRESH_COOLDOWN_MS - elapsed)
  subagentRefreshTimer = setTimeout(async () => {
    subagentRefreshTimer = null
    subagentLastRefreshAt = Date.now()
    await loadSubagents()
  }, delay)
}

function handleSubagentStreamPayload(payload = {}) {
  const outcome = String(payload?.outcome || payload?.spawn_outcome || '').trim()
  if (outcome === 'continue_current_batch') {
    subagentConflictNotice = {
      level: 'info',
      text: 'Current batch is still running. New request continues the same batch.',
      actions: ['keep_current', 'kill_batch']
    }
  } else if (outcome === 'queued_next_request') {
    subagentConflictNotice = {
      level: 'info',
      text: 'Current batch is running. Your next request has been queued.',
      actions: ['keep_current', 'kill_batch']
    }
  } else if (outcome === 'rejected_queue_full') {
    subagentConflictNotice = {
      level: 'warn',
      text: 'Subagent queue is full. Wait for completion or stop the active batch.',
      actions: ['kill_batch']
    }
  } else if (outcome === 'accepted' || outcome === 'accepted_from_queue') {
    subagentConflictNotice = null
  }
}

function handleSubagentStreamEvent(event) {
  if (!event) return
  if (event.lastEventId) {
    persistSubagentCursor(currentSessionKey, event.lastEventId)
  }
  let payload = {}
  try {
    payload = event.data ? JSON.parse(event.data) : {}
  } catch (error) {
    console.warn('[ChatPage] Failed to parse subagent status payload:', error)
    payload = {}
  }
  handleSubagentStreamPayload(payload)
  renderSubagentStrip()
  scheduleSubagentRefresh()
}

function startSubagentStatusStream() {
  if (!currentSessionKey || typeof EventSource === 'undefined') return
  if (typeof process !== 'undefined' && process.env && process.env.NODE_ENV === 'test') {
    return
  }
  stopSubagentStatusStream()
  const cursor = loadSubagentCursor(currentSessionKey)
  try {
    subagentEventSource = createSessionSubagentStatusStream(currentSessionKey, cursor)
  } catch (error) {
    console.error('[ChatPage] Failed to create subagent status stream:', error)
    return
  }
  subagentEventSource.addEventListener('subagent_status', handleSubagentStreamEvent)
  subagentEventSource.onerror = () => {
    if (!mounted || !currentSessionKey) return
    stopSubagentStatusStream()
    subagentReconnectTimer = setTimeout(() => {
      subagentReconnectTimer = null
      startSubagentStatusStream()
    }, SUBAGENT_STREAM_RECONNECT_MS)
  }
}

function stopSubagentStatusStream() {
  if (subagentRefreshTimer) {
    clearTimeout(subagentRefreshTimer)
    subagentRefreshTimer = null
  }
  if (subagentReconnectTimer) {
    clearTimeout(subagentReconnectTimer)
    subagentReconnectTimer = null
  }
  if (subagentEventSource) {
    subagentEventSource.removeEventListener('subagent_status', handleSubagentStreamEvent)
    subagentEventSource.close()
    subagentEventSource = null
  }
}

function restartSubagentStatusStream() {
  stopSubagentStatusStream()
  startSubagentStatusStream()
}

function ensureActiveSessionEntry() {
  if (!currentSessionKey) return
  const exists = sessionsCache.some((session) => session.session_key === currentSessionKey)
  if (!exists) {
    sessionsCache.unshift({
      session_key: currentSessionKey,
      title: 'New Chat',
      title_status: 'empty'
    })
  }
}

function renderSidebarContent(container) {
  const filtered = getFilteredSessions()
  const itemsHtml = filtered.map((session) => {
    const isActive = session.session_key === currentSessionKey
    const title = getSessionTitle(session)
    return `
      <div class="session-list-row${isActive ? ' active' : ''}">
        <button class="session-list-item" type="button" data-session-key="${escapeHtml(session.session_key)}">${escapeHtml(title)}</button>
        <button class="session-delete-btn" type="button" data-delete-session="${escapeHtml(session.session_key)}" aria-label="Delete">×</button>
      </div>
    `
  }).join('')

  container.innerHTML = `
    <div class="session-sidebar-shell">
      <div class="session-search-shell">
        <input id="session-search-input" class="session-search-input" type="search" placeholder="Search chats..." value="${escapeHtml(searchQuery)}" />
      </div>
      <div class="session-list">${itemsHtml}</div>
    </div>
  `

  const input = container.querySelector('#session-search-input')
  if (input) {
    input.addEventListener('input', (event) => {
      searchQuery = event.target.value || ''
      renderSidebarContent(container)
    })
  }

  container.querySelectorAll('[data-session-key]').forEach((button) => {
    button.addEventListener('click', handleSessionClick)
  })
  container.querySelectorAll('[data-delete-session]').forEach((button) => {
    button.addEventListener('click', handleDeleteSessionClick)
  })
}

function getFilteredSessions() {
  const normalizedQuery = searchQuery.trim().toLowerCase()
  if (!normalizedQuery) return sessionsCache
  return sessionsCache.filter((session) => getSessionTitle(session).toLowerCase().includes(normalizedQuery))
}

function getSessionTitle(session) {
  return (session?.title || '').trim() || 'New Chat'
}

function deriveConflictNoticeFromCache() {
  const candidates = [
    ...(subagentsCache.active || []),
    ...(subagentsCache.recent || [])
  ]
  for (const item of candidates) {
    const outcome = String(item?.spawn_outcome || '').trim()
    if (!outcome) continue
    if (outcome === 'continue_current_batch') {
      return {
        level: 'info',
        text: 'Current batch is still running. New request continues the same batch.',
        actions: ['keep_current', 'kill_batch']
      }
    }
    if (outcome === 'queued_next_request') {
      return {
        level: 'info',
        text: 'Current batch is running. Your next request has been queued.',
        actions: ['keep_current', 'kill_batch']
      }
    }
    if (outcome === 'rejected_queue_full') {
      return {
        level: 'warn',
        text: 'Subagent queue is full. Wait for completion or stop the active batch.',
        actions: ['kill_batch']
      }
    }
  }
  return null
}

async function handleSessionClick(event) {
  const nextKey = event.currentTarget.getAttribute('data-session-key')
  if (!nextKey || nextKey === currentSessionKey) return

  abortCurrentStream()
  setSessionKey(nextKey)
  currentSessionKey = nextKey
  await activateSession(nextKey)
  await loadAttachments()
  await loadSubagents()
  restartSubagentStatusStream()
  renderSidebarContent(document.getElementById('sidebar-dynamic-content'))
  syncHeaderTitle()
}

function handleUserTurnStarted({ sessionKey, messageText }) {
  const changedSession = sessionKey && sessionKey !== currentSessionKey
  currentSessionKey = sessionKey
  const draftTitle = buildDraftTitle(messageText)
  upsertSession({ session_key: sessionKey, title: draftTitle, title_status: 'draft' })
  const emptyState = pageContainer?.querySelector('#chat-empty-state')
  if (emptyState) {
    emptyState.classList.add('hidden')
  }
  pageContainer?.classList.remove('chat-empty-mode')
  if (changedSession) {
    restartSubagentStatusStream()
  }
  renderSidebarContent(document.getElementById('sidebar-dynamic-content'))
  syncHeaderTitle()
}

async function handleRunCompleted() {
  await loadSessions()
  await loadAttachments()
  await loadSubagents()
}

async function handleToolEvent({ toolName, phase }) {
  const normalizedToolName = String(toolName || '').trim()
  if (phase !== 'end') return
  if (normalizedToolName === 'sessions_spawn' || normalizedToolName === 'subagents') {
    await loadSubagents()
  }
}

function handleConversationStateChange({ hasMessages, agentInfo }) {
  const emptyState = pageContainer?.querySelector('#chat-empty-state')
  if (!emptyState) return

  currentAgentName = agentInfo?.name || currentAgentName
  const emptyTitle = emptyState.querySelector('.chat-empty-title')
  const emptyCopy = emptyState.querySelector('.chat-empty-copy')
  if (emptyTitle) {
    emptyTitle.textContent = currentAgentName
  }
  if (emptyCopy) {
    emptyCopy.textContent = agentInfo?.welcome_message || ''
  }

  emptyState.classList.toggle('hidden', hasMessages)
  pageContainer.classList.toggle('chat-empty-mode', !hasMessages)
  syncHeaderTitle(hasMessages)
}

function syncHeaderTitle(hasMessages = true) {
  const active = sessionsCache.find((session) => session.session_key === currentSessionKey)
  const title = hasMessages && active ? getSessionTitle(active) : currentAgentName
  updateHeaderTitleText(title || currentAgentName)
}

function upsertSession(nextSession) {
  const idx = sessionsCache.findIndex((session) => session.session_key === nextSession.session_key)
  if (idx >= 0) {
    sessionsCache[idx] = { ...sessionsCache[idx], ...nextSession }
    return
  }
  sessionsCache.unshift(nextSession)
}

function buildDraftTitle(messageText) {
  const cleaned = String(messageText || '').replace(/\s+/g, ' ').trim().replace(/[,.!?，。！？；：]+$/g, '')
  if (!cleaned) return 'New Chat'
  return cleaned.length > 24 ? `${cleaned.slice(0, 23).trim()}...` : cleaned
}

function bindDialogEvents(container) {
  const dialog = container.querySelector('#confirmDialog')
  if (!dialog) return

  const cancelBtn = dialog.querySelector('.btn-cancel')
  if (cancelBtn) {
    cancelBtn.addEventListener('click', hideConfirmDialog)
  }
}

function bindAttachmentEvents(container) {
  const uploadButton = container.querySelector('#chat-attachment-upload-btn')
  const fileInput = container.querySelector('#chat-attachment-input')
  if (!uploadButton || !fileInput) return

  uploadButton.addEventListener('click', () => {
    fileInput.click()
  })

  fileInput.addEventListener('change', async (event) => {
    const selectedFile = event.target.files?.[0]
    if (!selectedFile || !currentSessionKey) return
    try {
      await uploadSessionAttachment(currentSessionKey, selectedFile)
      await loadAttachments()
    } catch (error) {
      console.error('[ChatPage] Failed to upload attachment:', error)
    } finally {
      event.target.value = ''
    }
  })
}

function renderAttachmentStrip() {
  const container = pageContainer?.querySelector('#chat-attachment-content')
  if (!container) return

  const uploadItems = (attachmentsCache.uploads || []).map((item) => {
    const mode = item.injection_mode ? `<span class="attachment-chip-meta">${escapeHtml(item.injection_mode)}</span>` : ''
    return `<a class="attachment-chip" href="${escapeHtml(item.download_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.filename)}${mode}</a>`
  }).join('')

  const artifactItems = (attachmentsCache.artifacts || []).map((item) => {
    return `<a class="attachment-chip attachment-chip-output" href="${escapeHtml(item.download_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.filename)}</a>`
  }).join('')

  container.innerHTML = `
    <div class="attachment-strip-group">
      <span class="attachment-strip-label">Attachments</span>
      <div class="attachment-strip-items">${uploadItems || '<span class="attachment-strip-empty">None</span>'}</div>
    </div>
    <span class="attachment-strip-divider" aria-hidden="true"></span>
    <div class="attachment-strip-group">
      <span class="attachment-strip-label">Outputs</span>
      <div class="attachment-strip-items">${artifactItems || '<span class="attachment-strip-empty">None</span>'}</div>
    </div>
  `
}

function renderSubagentStrip() {
  const container = pageContainer?.querySelector('#chat-subagent-content')
  if (!container) return

  if (!subagentsCache.runtime_available) {
    container.innerHTML = `
      <div class="subagent-strip-empty-row">
        <span class="subagent-strip-title">Subagents</span>
        <span class="subagent-strip-empty">Runtime unavailable</span>
      </div>
    `
    return
  }

  const activeItems = (subagentsCache.active || []).slice(0, 6).map((item) => `
    <div class="subagent-pill is-active${item.stalled ? ' is-stalled' : ''}" data-run-id="${escapeHtml(item.run_id)}">
      <span class="subagent-pill-id">${escapeHtml(item.subagent_id)}</span>
      <span class="subagent-pill-state">${escapeHtml(item.status)}</span>
      ${item.stalled ? '<span class="subagent-pill-stalled">Possibly stuck</span>' : ''}
      <span class="subagent-pill-actions">
        <button class="subagent-pill-btn" type="button" data-sa-steer="${escapeHtml(item.run_id)}">Steer</button>
        <button class="subagent-pill-btn danger" type="button" data-sa-kill="${escapeHtml(item.run_id)}">Kill</button>
        <button class="subagent-pill-btn" type="button" data-sa-open="${escapeHtml(item.child_session_key)}">Open Result</button>
      </span>
    </div>
  `).join('')

  const recentItems = (subagentsCache.recent || []).slice(0, 6).map((item) => `
    <div class="subagent-pill">
      <span class="subagent-pill-id">${escapeHtml(item.subagent_id)}</span>
      <span class="subagent-pill-state">${escapeHtml(item.status)}</span>
      ${(item.status === 'failed' || item.status === 'timed_out')
        ? `<button class="subagent-pill-btn" type="button" data-sa-retry="${escapeHtml(item.run_id)}">Retry</button>
           <button class="subagent-pill-btn" type="button" data-sa-retry-edit="${escapeHtml(item.run_id)}">Retry + Edit</button>`
        : ''}
      <button class="subagent-pill-btn" type="button" data-sa-open="${escapeHtml(item.child_session_key)}">Open Result</button>
    </div>
  `).join('')

  const activeCount = (subagentsCache.active || []).length
  const recentCount = (subagentsCache.recent || []).length
  const queueDepth = Number(subagentsCache.queue_depth || 0)
  const activeBatch = String(subagentsCache.active_batch_id || '')
  const notice = subagentConflictNotice
  const noticeHtml = notice
    ? `
      <div class="subagent-strip-notice ${escapeHtml(notice.level || 'info')}">
        <span class="subagent-strip-notice-text">${escapeHtml(notice.text || '')}</span>
        <span class="subagent-strip-notice-actions">
          ${(notice.actions || []).includes('keep_current')
            ? '<button class="subagent-pill-btn" type="button" data-sa-notice-keep="1">Keep Current</button>'
            : ''}
          ${(notice.actions || []).includes('kill_batch') && activeBatch
            ? '<button class="subagent-pill-btn danger" type="button" data-sa-notice-kill-batch="1">Kill Batch</button>'
            : ''}
        </span>
      </div>
    `
    : ''
  container.innerHTML = `
    <div class="subagent-strip-row">
      <span class="subagent-strip-title">Subagents</span>
      <span class="subagent-strip-summary">${activeCount} active · ${recentCount} recent · ${queueDepth} queued</span>
      ${activeBatch ? `<span class="subagent-strip-batch">Batch ${escapeHtml(activeBatch.slice(-8))}</span>` : ''}
      <button class="subagent-strip-killall" type="button" data-sa-kill-all="1">Kill All</button>
      ${activeBatch ? '<button class="subagent-strip-killall" type="button" data-sa-kill-batch="1">Kill Batch</button>' : ''}
      ${noticeHtml}
      <div class="subagent-strip-items">${activeItems || recentItems || '<span class="subagent-strip-empty">None</span>'}</div>
    </div>
  `

  container.querySelectorAll('[data-sa-kill]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const runId = btn.getAttribute('data-sa-kill')
      if (runId) {
        void handleKillSubagent(runId)
      }
    })
  })
  container.querySelectorAll('[data-sa-steer]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const runId = btn.getAttribute('data-sa-steer')
      if (runId) {
        void handleSteerSubagent(runId)
      }
    })
  })
  container.querySelectorAll('[data-sa-open]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const childSessionKey = btn.getAttribute('data-sa-open')
      if (childSessionKey) {
        void openSubagentSession(childSessionKey)
      }
    })
  })
  container.querySelectorAll('[data-sa-retry]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const runId = btn.getAttribute('data-sa-retry')
      if (runId) {
        void handleRetrySubagent(runId, false)
      }
    })
  })
  container.querySelectorAll('[data-sa-retry-edit]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const runId = btn.getAttribute('data-sa-retry-edit')
      if (runId) {
        void handleRetrySubagent(runId, true)
      }
    })
  })
  const killAllBtn = container.querySelector('[data-sa-kill-all]')
  if (killAllBtn) {
    killAllBtn.addEventListener('click', () => {
      void handleKillSubagent('all')
    })
  }
  const killBatchBtn = container.querySelector('[data-sa-kill-batch]')
  if (killBatchBtn && activeBatch) {
    killBatchBtn.addEventListener('click', () => {
      void handleKillSubagent(`batch:${activeBatch}`)
    })
  }
  const keepNoticeBtn = container.querySelector('[data-sa-notice-keep]')
  if (keepNoticeBtn) {
    keepNoticeBtn.addEventListener('click', () => {
      subagentConflictNotice = null
      renderSubagentStrip()
    })
  }
  const killNoticeBatchBtn = container.querySelector('[data-sa-notice-kill-batch]')
  if (killNoticeBatchBtn && activeBatch) {
    killNoticeBatchBtn.addEventListener('click', () => {
      void handleKillSubagent(`batch:${activeBatch}`)
    })
  }
}

async function handleKillSubagent(target) {
  if (!currentSessionKey) return
  try {
    await killSessionSubagent(currentSessionKey, target)
    subagentConflictNotice = null
    await loadSubagents()
  } catch (error) {
    console.error('[ChatPage] Failed to kill subagent:', error)
    subagentConflictNotice = {
      level: 'warn',
      text: 'Unable to stop subagent batch. Please retry in a moment.',
      actions: ['keep_current']
    }
    renderSubagentStrip()
  }
}

async function handleSteerSubagent(target) {
  if (!currentSessionKey) return
  const steerMessage = window.prompt('Steer message for subagent:')
  if (!steerMessage) return
  try {
    await steerSessionSubagent(currentSessionKey, target, steerMessage)
    await loadSubagents()
  } catch (error) {
    console.error('[ChatPage] Failed to steer subagent:', error)
    subagentConflictNotice = {
      level: 'warn',
      text: 'Steer was rejected for this run. It may already be terminal.',
      actions: ['keep_current']
    }
    renderSubagentStrip()
  }
}

async function handleRetrySubagent(target, withEdit = false) {
  if (!currentSessionKey) return
  let mode = 'retry_same_context'
  let editedTask = ''
  if (withEdit) {
    mode = 'retry_with_edit'
    editedTask = window.prompt('Edit subagent task before retry:') || ''
    if (!editedTask.trim()) return
  }
  try {
    await retrySessionSubagent(currentSessionKey, target, mode, editedTask)
    subagentConflictNotice = null
    await loadSubagents()
  } catch (error) {
    console.error('[ChatPage] Failed to retry subagent:', error)
    subagentConflictNotice = {
      level: 'warn',
      text: 'Retry was rejected. Wait for current batch to finish or kill active batch first.',
      actions: ['keep_current', 'kill_batch']
    }
    renderSubagentStrip()
  }
}

async function openSubagentSession(childSessionKey) {
  if (!childSessionKey || childSessionKey === currentSessionKey) return
  abortCurrentStream()
  setSessionKey(childSessionKey)
  currentSessionKey = childSessionKey
  upsertSession({
    session_key: childSessionKey,
    title: `Subagent ${childSessionKey.slice(-6)}`,
    title_status: 'draft'
  })
  await activateSession(childSessionKey)
  await loadAttachments()
  await loadSubagents()
  restartSubagentStatusStream()
  renderSidebarContent(document.getElementById('sidebar-dynamic-content'))
  syncHeaderTitle()
}

function handleDeleteSessionClick(event) {
  event.stopPropagation()
  const sessionKey = event.currentTarget.getAttribute('data-delete-session')
  if (!sessionKey) return
  showConfirmDialog(sessionKey)
}

function showConfirmDialog(sessionKey) {
  const dialog = pageContainer?.querySelector('#confirmDialog')
  if (!dialog) return
  const message = dialog.querySelector('#confirmMessage')
  const confirmBtn = dialog.querySelector('.btn-confirm')
  if (message) {
    message.textContent = t('dialog.confirmMessage') || 'Delete this conversation?'
  }
  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      await deleteCurrentSession(sessionKey)
    }
  }
  dialog.classList.remove('hidden')
}

function hideConfirmDialog() {
  const dialog = pageContainer?.querySelector('#confirmDialog')
  if (dialog) dialog.classList.add('hidden')
}

async function deleteCurrentSession(sessionKey) {
  try {
    await deleteSession(sessionKey)
    sessionsCache = sessionsCache.filter((session) => session.session_key !== sessionKey)
    if (sessionKey === currentSessionKey) {
      const nextSession = sessionsCache[0]
      currentSessionKey = nextSession?.session_key || null
      setSessionKey(currentSessionKey)
      await activateSession(currentSessionKey)
      await loadAttachments()
      await loadSubagents()
      restartSubagentStatusStream()
    }
    renderSidebarContent(document.getElementById('sidebar-dynamic-content'))
    syncHeaderTitle()
  } catch (error) {
    console.error('[ChatPage] Failed to delete session:', error)
  } finally {
    hideConfirmDialog()
  }
}

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}
