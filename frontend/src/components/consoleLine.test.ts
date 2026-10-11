import { describe, expect, it } from 'vitest'
import type { CommandArg, ConsoleCommand } from '../api/client'
import { buildLine, quote } from './consoleLine'

const arg = (name: string, kind: string, rest = false): CommandArg => ({
  name,
  kind,
  required: true,
  rest,
  default: null,
  choices: [],
})

const send: ConsoleCommand = {
  name: 'send',
  help: '',
  raw: false,
  args: [arg('player_name', 'player'), arg('item_name', 'item', true)],
}
const release: ConsoleCommand = {
  name: 'release',
  help: '',
  raw: true,
  args: [arg('player_name', 'player')],
}

describe('console lines', () => {
  it('quotes only the words that need it, as shlex reads them', () => {
    expect(quote('Knight')).toBe('Knight')
    expect(quote('Big Knight')).toBe('"Big Knight"')
    expect(quote("Link's House")).toBe('"Link\'s House"')
    expect(quote('say "hi" \\o/')).toBe('"say \\"hi\\" \\\\o/"')
  })

  it('builds a command with its arguments', () => {
    expect(buildLine(send, ['Big Knight', 'Progressive Sword'])).toBe(
      '/send "Big Knight" "Progressive Sword"',
    )
    expect(buildLine(send, ['Knight', ''])).toBe('/send Knight')
    expect(buildLine(send, ['', 'Hookshot'])).toBe('/send "" Hookshot')
    expect(buildLine(send, [])).toBe('/send')
  })

  it('leaves a raw command unquoted', () => {
    expect(buildLine(release, ['Big Knight'])).toBe('/release Big Knight')
  })
})
