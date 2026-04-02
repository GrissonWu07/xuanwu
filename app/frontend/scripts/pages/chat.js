/**
 * chat.js - Chat Page Module
 */

import { initSession, getSessionKey, setSessionKey } from '../session-manager.js'
import { initChat, activateSession, abortCurrentStream, getCurrentAgentInfo } from '../chat-ui.js'
import { listSessions, deleteSession, listSessionAttachments, uploadSessionAttachment } from '../api-client.js'
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
    onRunCompleted: handleRunCompleted
  })

  currentAgentName = getCurrentAgentInfo()?.name || currentAgentName
  await loadSessions()
  await loadAttachments()
  bindDialogEvents(container)
  bindAttachmentEvents(container)
  mounted = true
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

async function handleSessionClick(event) {
  const nextKey = event.currentTarget.getAttribute('data-session-key')
  if (!nextKey || nextKey === currentSessionKey) return

  abortCurrentStream()
  setSessionKey(nextKey)
  currentSessionKey = nextKey
  await activateSession(nextKey)
  await loadAttachments()
  renderSidebarContent(document.getElementById('sidebar-dynamic-content'))
  syncHeaderTitle()
}

function handleUserTurnStarted({ sessionKey, messageText }) {
  currentSessionKey = sessionKey
  const draftTitle = buildDraftTitle(messageText)
  upsertSession({ session_key: sessionKey, title: draftTitle, title_status: 'draft' })
  const emptyState = pageContainer?.querySelector('#chat-empty-state')
  if (emptyState) {
    emptyState.classList.add('hidden')
  }
  pageContainer?.classList.remove('chat-empty-mode')
  renderSidebarContent(document.getElementById('sidebar-dynamic-content'))
  syncHeaderTitle()
}

async function handleRunCompleted() {
  await loadSessions()
  await loadAttachments()
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
