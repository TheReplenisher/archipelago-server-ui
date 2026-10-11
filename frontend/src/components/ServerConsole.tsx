import { Button, Code, Group, Select, Stack, Text, TextInput } from '@mantine/core'
import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  getConsoleNames,
  listCommands,
  sendCommand,
  type CommandArg,
  type ConsoleCommand,
  type ConsoleNames,
} from '../api/client'
import { buildLine } from './consoleLine'

const HISTORY = 20
/** Matches shown at a time in a searchable list: a game can have thousands of items. */
const LIST_LIMIT = 100

/** "player_name" → "Player", "option_value" → "Option value". */
function argLabel(arg: CommandArg): string {
  const words = arg.name.replace(/_name$/, '').replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

interface ArgInputProps {
  arg: CommandArg
  value: string
  onChange: (value: string) => void
  names: ConsoleNames | null
  /** The game of the player picked before this argument, for item and location lists. */
  game: string | null
}

/** The right input for one argument: a searchable list where there is one to pick from,
 * else text. Without the game's names, players, items and locations are text too. */
function ArgInput({ arg, value, onChange, names, game }: ArgInputProps) {
  const label = argLabel(arg)
  const placeholder = arg.default ? `${arg.default} if empty` : arg.required ? '' : 'optional'
  let list: string[] | null = null
  let waiting = false
  if (arg.kind === 'option' && arg.choices.length > 0) list = arg.choices
  else if (names && arg.kind === 'player') list = names.players.map((p) => p.name)
  else if (names && (arg.kind === 'item' || arg.kind === 'location')) {
    const lists = game ? names.games[game] : undefined
    list = lists ? (arg.kind === 'item' ? lists.items : lists.locations) : []
    waiting = !game
  }
  if (list)
    return (
      <Select
        label={label}
        placeholder={waiting ? 'Pick the player first' : placeholder}
        data={list}
        value={value || null}
        onChange={(v) => onChange(v ?? '')}
        searchable
        clearable
        limit={LIST_LIMIT}
        nothingFoundMessage="No match"
        disabled={waiting}
        w={arg.kind === 'player' ? 160 : 240}
      />
    )
  return (
    <TextInput
      label={label}
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.currentTarget.value)}
      inputMode={arg.kind === 'number' ? 'numeric' : undefined}
      w={arg.kind === 'number' ? 100 : 200}
    />
  )
}

/** MultiServer's console, while the server runs. Pick a command and fill in its arguments
 * from the game's own names, or type any line by hand; the up and down arrows recall the
 * lines sent. Its replies go to the server's log until the live feed (#27) shows them. */
export function ServerConsole() {
  const [text, setText] = useState('')
  const [sent, setSent] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [recalled, setRecalled] = useState<number | null>(null) // index into `sent`
  const [commands, setCommands] = useState<ConsoleCommand[]>([])
  const [names, setNames] = useState<ConsoleNames | null>(null)
  const [picked, setPicked] = useState<ConsoleCommand | null>(null)
  const [values, setValues] = useState<string[]>([])

  useEffect(() => {
    const controller = new AbortController()
    listCommands(controller.signal)
      .then(setCommands)
      .catch(() => setCommands([]))
    getConsoleNames(controller.signal)
      .then(setNames)
      .catch(() => setNames(null))
    return () => controller.abort()
  }, [])

  const pick = (name: string | null) => {
    const command = commands.find((c) => c.name === name) ?? null
    const empty = command ? command.args.map(() => '') : []
    setPicked(command)
    setValues(empty)
    setText(command ? buildLine(command, empty) : '')
    setRecalled(null)
  }

  const setArg = (i: number, value: string) => {
    if (!picked) return
    const next = picked.args.map((arg, j) => {
      if (j === i) return value
      // A new player means another game's items and locations.
      if (j > i && picked.args[i].kind === 'player' && ['item', 'location'].includes(arg.kind))
        return ''
      return values[j] ?? ''
    })
    setValues(next)
    setText(buildLine(picked, next))
  }

  const gameBefore = (i: number): string | null => {
    for (let j = i - 1; picked && j >= 0; j--)
      if (picked.args[j].kind === 'player')
        return names?.players.find((p) => p.name === values[j])?.game ?? null
    return null
  }

  const recall = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowUp' && sent.length > 0) {
      event.preventDefault()
      const i = recalled === null ? sent.length - 1 : Math.max(0, recalled - 1)
      setRecalled(i)
      setText(sent[i])
    } else if (event.key === 'ArrowDown' && recalled !== null) {
      event.preventDefault()
      const i = recalled + 1
      setRecalled(i < sent.length ? i : null)
      setText(i < sent.length ? sent[i] : '')
    }
  }

  const send = async (event: FormEvent) => {
    event.preventDefault()
    const line = text.trim()
    if (!line) return
    setBusy(true)
    setError(null)
    try {
      await sendCommand(line)
      setSent((s) => [...s, line].slice(-HISTORY))
      setText('')
      setRecalled(null)
      setPicked(null)
      setValues([])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={send}>
      <Stack gap={4}>
        {commands.length > 0 && (
          <Group gap="xs" align="flex-end">
            <Select
              label="Command"
              placeholder="Pick a command"
              data={commands.map((c) => ({ value: c.name, label: `/${c.name}` }))}
              value={picked?.name ?? null}
              onChange={pick}
              searchable
              clearable
              w={180}
            />
            {picked?.args.map((arg, i) => (
              <ArgInput
                key={`${picked.name}:${arg.name}`}
                arg={arg}
                value={values[i] ?? ''}
                onChange={(v) => setArg(i, v)}
                names={names}
                game={gameBefore(i)}
              />
            ))}
          </Group>
        )}
        {picked?.help && (
          <Text size="xs" c="dimmed">
            {picked.help}
          </Text>
        )}
        <Group gap="xs" align="flex-end">
          <TextInput
            label="Console"
            placeholder="/players, or a message to everyone"
            maxLength={1000}
            value={text}
            onChange={(e) => {
              setText(e.currentTarget.value)
              setRecalled(null)
            }}
            onKeyDown={recall}
            error={error}
            style={{ flex: 1 }}
          />
          <Button type="submit" variant="light" loading={busy}>
            Send
          </Button>
        </Group>
        {sent.length > 0 && (
          <Code block aria-label="Sent commands">
            {sent.join('\n')}
          </Code>
        )}
        <Text size="xs" c="dimmed">
          The server's replies go to its log; the live server feed is still to come.
        </Text>
      </Stack>
    </form>
  )
}
