export function parseDailyAt(value) {
  const text = String(value)
  const match = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(text)
  if (!match) {
    throw new RangeError(`invalid daily time "${text}"; expected HH:MM`)
  }
  return { hour: Number(match[1]), minute: Number(match[2]) }
}

function localParts(date, timeZone) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const parts = {}
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== 'literal') parts[part.type] = Number(part.value)
  }
  return parts
}

function zoneOffsetMs(date, timeZone) {
  const parts = localParts(date, timeZone)
  const asUtc = Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second,
  )
  return asUtc - Math.floor(date.getTime() / 1000) * 1000
}

function zonedToUtc(year, month, day, hour, minute, timeZone) {
  const wallClock = Date.UTC(year, month - 1, day, hour, minute, 0, 0)
  let guess = wallClock
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const next = wallClock - zoneOffsetMs(new Date(guess), timeZone)
    if (next === guess) break
    guess = next
  }
  return guess
}

export function nextRunAt(now, { at = '09:00', timeZone = 'UTC' } = {}) {
  const current = now instanceof Date ? new Date(now.getTime()) : new Date(now)
  if (Number.isNaN(current.getTime())) throw new RangeError('now is not a valid date')
  const target = parseDailyAt(at)
  const parts = localParts(current, timeZone)
  for (let dayOffset = 0; dayOffset <= 2; dayOffset += 1) {
    const localDay = new Date(
      Date.UTC(parts.year, parts.month - 1, parts.day + dayOffset),
    )
    const candidate = zonedToUtc(
      localDay.getUTCFullYear(),
      localDay.getUTCMonth() + 1,
      localDay.getUTCDate(),
      target.hour,
      target.minute,
      timeZone,
    )
    if (candidate > current.getTime()) return new Date(candidate)
  }
  return new Date(
    zonedToUtc(
      parts.year,
      parts.month,
      parts.day + 2,
      target.hour,
      target.minute,
      timeZone,
    ),
  )
}

export function createDailyCron({
  at = '09:00',
  timeZone = 'UTC',
  run,
  now = () => new Date(),
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout,
  onError = () => {},
} = {}) {
  if (typeof run !== 'function') throw new TypeError('run must be a function')
  parseDailyAt(at)
  new Intl.DateTimeFormat('en-US', { timeZone }).format(new Date())

  let stopped = true
  let timer = null
  let next = null

  const schedule = () => {
    const current = now()
    next = nextRunAt(current, { at, timeZone })
    const delay = Math.max(0, next.getTime() - current.getTime())
    timer = setTimeoutFn(async () => {
      timer = null
      if (stopped) return
      try {
        await run()
      } catch (error) {
        onError(error)
      }
      if (!stopped) schedule()
    }, delay)
    timer?.unref?.()
  }

  return {
    get running() {
      return !stopped
    },
    get nextRunAt() {
      return next === null ? null : new Date(next.getTime())
    },
    start() {
      if (!stopped) return this
      stopped = false
      schedule()
      return this
    },
    stop() {
      stopped = true
      if (timer !== null) {
        clearTimeoutFn(timer)
        timer = null
      }
      next = null
      return this
    },
    async runNow() {
      return await run()
    },
  }
}
