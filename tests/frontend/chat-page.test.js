beforeEach(() => {
  jest.resetModules()
  document.body.innerHTML = `
    <div id="sidebar-dynamic-content"></div>
    <div id="page-root"></div>
  `
  sessionStorage.clear()
  global.fetch = jest.fn((url, options = {}) => {
    const target = String(url)
    if (target.includes('/api/sessions/session-a/subagents')) {
      if (target.includes('/kill')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', killed: 1 })
        })
      }
      if (target.includes('/steer')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'accepted', run_id: 'subrun-2' })
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          runtime_available: true,
          total: 1,
          active: [
            {
              run_id: 'subrun-1',
              subagent_id: 'sub-1',
              status: 'running',
              task: 'collect data',
              child_session_key: 'agent:main:user:default:web:dm:default:topic:child-1',
              depth: 1,
              created_at: '2026-03-28T09:00:00Z',
              started_at: '2026-03-28T09:00:01Z',
              ended_at: null,
              output: '',
              error: ''
            }
          ],
          recent: []
        })
      })
    }
    if (target.endsWith('/api/sessions/session-a/attachments')) {
      if (options.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            upload: {
              entry_id: 'upload-1',
              filename: 'brief.txt',
              batch_id: '1711612345',
              relative_path: '1711612345/uploads/upload-1-brief.txt',
              size_bytes: 12,
              content_type: 'text/plain',
              injection_mode: 'full',
              created_at: '2026-03-28T09:00:00Z',
              download_url: '/api/sessions/session-a/attachments/upload-1/content'
            }
          })
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          uploads: [
            {
              entry_id: 'upload-1',
              filename: 'brief.txt',
              batch_id: '1711612345',
              relative_path: '1711612345/uploads/upload-1-brief.txt',
              size_bytes: 12,
              content_type: 'text/plain',
              injection_mode: 'full',
              created_at: '2026-03-28T09:00:00Z',
              download_url: '/api/sessions/session-a/attachments/upload-1/content'
            }
          ],
          artifacts: [
            {
              entry_id: 'artifact-1',
              filename: 'report.md',
              batch_id: '1711612455',
              relative_path: '1711612455/workspace/report.md',
              size_bytes: 24,
              status: 'ready',
              created_at: '2026-03-28T09:05:00Z',
              download_url: '/api/sessions/session-a/attachments/artifact-1/content'
            }
          ]
        })
      })
    }
    if (target.endsWith('/api/sessions/threads')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ session_key: 'session-a' })
      })
    }
    if (target.endsWith('/api/agent/info')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          name: 'AtlasClaw Enterprise AI Assistant',
          welcome_message: 'Welcome'
        })
      })
    }
    if (target.endsWith('/api/sessions/session-a/history')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ messages: [] })
      })
    }
    if (target.endsWith('/api/sessions')) {
      if (options.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ session_key: 'session-a' })
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([
          { session_key: 'session-a', title: 'Query approvals', title_status: 'final' },
          { session_key: 'session-b', title: 'Create virtual machine', title_status: 'final' }
        ])
      })
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({})
    })
  })
})

const sessionStorageMock = (() => {
  let store = {}
  return {
    getItem: jest.fn((key) => store[key] || null),
    setItem: jest.fn((key, value) => { store[key] = value }),
    removeItem: jest.fn((key) => { delete store[key] }),
    clear: jest.fn(() => { store = {} })
  }
})()

Object.defineProperty(global, 'sessionStorage', { value: sessionStorageMock })

describe('chat page', () => {
  test('mount renders searchable session titles without date grouping', async () => {
    const chatPage = await import('../../app/frontend/scripts/pages/chat.js')
    const container = document.getElementById('page-root')

    await chatPage.mount(container)

    const sidebar = document.getElementById('sidebar-dynamic-content')
    expect(sidebar.textContent).toContain('Query approvals')
    expect(sidebar.textContent).toContain('Create virtual machine')
    expect(sidebar.textContent).not.toContain('Today')
    expect(container.textContent).toContain('brief.txt')
    expect(container.textContent).toContain('report.md')
    expect(container.textContent).toContain('Subagents')
    expect(container.textContent).toContain('sub-1')

    const searchInput = sidebar.querySelector('#session-search-input')
    searchInput.value = 'approvals'
    searchInput.dispatchEvent(new Event('input'))

    expect(sidebar.textContent).toContain('Query approvals')
    expect(sidebar.textContent).not.toContain('Create virtual machine')
  })

  test('user turn hides empty state immediately before assistant response returns', async () => {
    jest.resetModules()

    let capturedCallbacks = null
    jest.unstable_mockModule('../../app/frontend/scripts/chat-ui.js', () => ({
      initChat: jest.fn(async (_element, callbacks = {}) => {
        capturedCallbacks = callbacks
      }),
      activateSession: jest.fn(async () => false),
      refreshActiveSessionHistory: jest.fn(async () => false),
      abortCurrentStream: jest.fn(),
      getCurrentAgentInfo: jest.fn(() => ({ name: 'AtlasClaw Enterprise AI Assistant' }))
    }))

    const chatPage = await import('../../app/frontend/scripts/pages/chat.js')
    const container = document.getElementById('page-root')

    await chatPage.mount(container)

    capturedCallbacks.onConversationStateChange({
      hasMessages: false,
      agentInfo: {
        name: 'AtlasClaw Enterprise AI Assistant',
        welcome_message: 'Welcome'
      }
    })

    const emptyState = container.querySelector('#chat-empty-state')
    expect(emptyState.classList.contains('hidden')).toBe(false)

    capturedCallbacks.onUserTurnStarted({
      sessionKey: 'session-a',
      messageText: '你好'
    })

    expect(emptyState.classList.contains('hidden')).toBe(true)
    expect(container.classList.contains('chat-empty-mode')).toBe(false)
  })

  test('upload button posts files to the attachment endpoint', async () => {
    const chatPage = await import('../../app/frontend/scripts/pages/chat.js')
    const container = document.getElementById('page-root')

    await chatPage.mount(container)

    const uploadButton = container.querySelector('#chat-attachment-upload-btn')
    const fileInput = container.querySelector('#chat-attachment-input')
    expect(uploadButton).not.toBeNull()
    expect(fileInput).not.toBeNull()

    const clickSpy = jest.spyOn(fileInput, 'click').mockImplementation(() => {})
    uploadButton.click()
    expect(clickSpy).toHaveBeenCalled()

    const file = new File(['hello world'], 'brief.txt', { type: 'text/plain' })
    Object.defineProperty(fileInput, 'files', {
      configurable: true,
      value: [file]
    })
    fileInput.dispatchEvent(new Event('change'))

    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/sessions\/session-a\/attachments$/),
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData)
      })
    )
  })
})
