import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sockets = []

vi.mock('axios', () => ({
  default: {
    get: vi.fn()
  }
}))

vi.mock('reconnecting-websocket', () => ({
  default: class FakeReconnectingWebSocket {
    constructor(url) {
      this.url = url
      sockets.push(this)
    }
  }
}))

import axios from 'axios'
import { useMowerStore } from './mower'
import websocketLogContract from './websocket-log-contract.json'

describe('WebUI scene snapshot contract', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sockets.length = 0
    axios.get.mockReset()
  })

  it('loads the latest snapshot once when preview opens or is re-enabled', async () => {
    axios.get.mockResolvedValue({ data: 'latest.jpg' })
    const store = useMowerStore()

    await store.set_scene_preview(true)
    await store.set_scene_preview(false)
    await store.set_scene_preview(true)

    expect(axios.get).toHaveBeenCalledTimes(2)
    expect(axios.get).toHaveBeenNthCalledWith(1, '/latest-screenshot')
    expect(store.sc_uri).toBe('latest.jpg')
    expect(store.sc_revision).toBe(2)
  })

  it('loads the latest snapshot once when the page opens with preview disabled', async () => {
    axios.get.mockResolvedValue({ data: 'latest.jpg' })
    const store = useMowerStore()

    await store.refresh_scene_snapshot()

    expect(axios.get).toHaveBeenCalledTimes(1)
    expect(axios.get).toHaveBeenCalledWith('/latest-screenshot')
    expect(store.sc_uri).toBe('latest.jpg')
    expect(store.sc_revision).toBe(1)
  })

  it('loads the latest snapshot once on websocket reconnection while preview is off', async () => {
    axios.get.mockResolvedValue({ data: 'latest.jpg' })
    const store = useMowerStore()

    store.listen_ws()
    await sockets[0].onopen()
    await sockets[0].onopen()

    expect(axios.get).toHaveBeenCalledTimes(1)
    expect(store.sc_revision).toBe(1)
  })

  it('refreshes once for a scene message and retains only the latest 100 lines', async () => {
    axios.get.mockResolvedValue({ data: 'latest.jpg' })
    const store = useMowerStore()
    await store.set_scene_preview(true)
    store.listen_ws()
    const lines = Array.from({ length: 105 }, (_, index) => `line-${index}`)

    sockets[0].onmessage({
      data: JSON.stringify({ type: 'log', data: lines.join('\n'), screenshot: 'scene.jpg' })
    })

    expect(store.log_lines).toHaveLength(100)
    expect(store.log_lines[0]).toBe('line-5')
    expect(store.sc_uri).toBe('scene.jpg')
    expect(store.sc_revision).toBe(2)
  })

  it('retains 100 actual lines when websocket text ends with CRLF', () => {
    const store = useMowerStore()
    store.listen_ws()
    const lines = Array.from({ length: 105 }, (_, index) => `line-${index}`)

    sockets[0].onmessage({
      data: JSON.stringify({ type: 'log', data: `${lines.join('\r\n')}\r\n` })
    })

    expect(store.log_lines).toHaveLength(100)
    expect(store.log_lines[0]).toBe('line-5')
    expect(store.log_lines[99]).toBe('line-104')
  })

  it('renders public logger websocket text on desktop and mobile', () => {
    const store = useMowerStore()
    store.listen_ws()

    sockets[0].onmessage({
      data: JSON.stringify({ type: 'log', data: websocketLogContract.backendData })
    })

    expect(store.log).toBe(websocketLogContract.desktopLog)
    expect(store.log_mobile).toBe(websocketLogContract.mobileLog)
  })
})
