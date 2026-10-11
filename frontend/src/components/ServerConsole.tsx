import { Button, Code, Group, Stack, Text, TextInput } from '@mantine/core'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { sendCommand } from '../api/client'

const HISTORY = 20

/** Free-text input for MultiServer's console, while the server runs, with the lines sent
 * recalled by the up and down arrows. Its replies go to the server's log until the live
 * feed (#27) shows them. */
export function ServerConsole() {
  const [text, setText] = useState('')
  const [sent, setSent] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [recalled, setRecalled] = useState<number | null>(null) // index into `sent`

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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={send}>
      <Stack gap={4}>
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
