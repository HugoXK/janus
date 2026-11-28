import assert from 'node:assert/strict'
import test from 'node:test'

import { createDailyCron, nextRunAt, parseDailyAt } from './cron.js'

test('parseDailyAt accepts HH:MM and rejects invalid times', () => {
  assert.deepEqual(parseDailyAt('09:30'), { hour: 9, minute: 30 })
  assert.deepEqual(parseDailyAt('0:05'), { hour: 0, minute: 5 })
  assert.throws(() => parseDailyAt('24:00'), /invalid daily time/)
  assert.throws(() => parseDailyAt('9:60'), /invalid daily time/)
  assert.throws(() => parseDailyAt('morning'), /invalid daily time/)
})

test('nextRunAt uses the requested timezone', () => {
  assert.equal(
    nextRunAt(new Date('2026-01-02T08:00:00Z'), { at: '09:30', timeZone: 'UTC' }).toISOString(),
    '2026-01-02T09:30:00.000Z',
  )
  assert.equal(
    nextRunAt(new Date('2026-01-02T12:00:00Z'), {
      at: '09:30',
      timeZone: 'America/New_York',
    }).toISOString(),
    '2026-01-02T14:30:00.000Z',
  )
  assert.equal(
    nextRunAt(new Date('2026-07-02T12:00:00Z'), {
      at: '09:30',
      timeZone: 'America/New_York',
    }).toISOString(),
    '2026-07-02T13:30:00.000Z',
  )
})

test('nextRunAt rolls over to the next local day', () => {
  assert.equal(
    nextRunAt(new Date('2026-01-02T09:30:00Z'), { at: '09:30', timeZone: 'UTC' }).toISOString(),
    '2026-01-03T09:30:00.000Z',
  )
  assert.equal(
    nextRunAt(new Date('2026-01-02T15:00:00Z'), {
      at: '09:30',
      timeZone: 'America/New_York',
    }).toISOString(),
    '2026-01-03T14:30:00.000Z',
  )
  assert.equal(
    nextRunAt(new Date('2026-01-02T16:00:00Z'), {
      at: '09:30',
      timeZone: 'Asia/Shanghai',
    }).toISOString(),
    '2026-01-03T01:30:00.000Z',
  )
})

test('createDailyCron schedules, runs, and stops', async () => {
  let scheduled = null
  let calls = 0
  let cleared = 0
  const now = () => new Date('2026-01-02T08:00:00Z')
  const cron = createDailyCron({
    at: '09:00',
    timeZone: 'UTC',
    run: async () => {
      calls += 1
    },
    now,
    setTimeoutFn: (fn, delay) => {
      scheduled = { fn, delay }
      return 1
    },
    clearTimeoutFn: () => {
      cleared += 1
    },
  })

  assert.equal(cron.running, false)
  assert.equal(cron.nextRunAt, null)
  cron.start()
  assert.equal(cron.running, true)
  assert.equal(scheduled.delay, 60 * 60 * 1000)
  assert.equal(cron.nextRunAt.toISOString(), '2026-01-02T09:00:00.000Z')

  await scheduled.fn()
  assert.equal(calls, 1)
  assert.equal(cron.running, true)

  cron.stop()
  assert.equal(cron.running, false)
  assert.equal(cleared, 1)
  assert.equal(cron.nextRunAt, null)
})

test('createDailyCron forwards failures without stopping', async () => {
  const errors = []
  let scheduled = null
  let calls = 0
  const cron = createDailyCron({
    at: '09:00',
    timeZone: 'UTC',
    run: async () => {
      calls += 1
      if (calls === 1) throw new Error('boom')
    },
    now: () => new Date('2026-01-02T08:00:00Z'),
    setTimeoutFn: (fn) => {
      scheduled = fn
      return 1
    },
    clearTimeoutFn: () => {},
    onError: (error) => errors.push(error.message),
  })

  cron.start()
  await scheduled()
  assert.deepEqual(errors, ['boom'])
  assert.equal(cron.running, true)
})

test('createDailyCron rejects bad configuration', () => {
  assert.throws(() => createDailyCron({ run: 'nope' }), /run must be a function/)
  assert.throws(
    () => createDailyCron({ run: () => {}, timeZone: 'Not/AZone' }),
    /Invalid time zone/i,
  )
})
