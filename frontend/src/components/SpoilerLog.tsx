import {
  Alert,
  Anchor,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  TextInput,
} from '@mantine/core'
import { IconDownload, IconEyeOff } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { getSpoiler, getSpoilerText, spoilerUrl, type SpoilerInfo } from '../api/client'

/** Above this the log is only offered as a download: a browser struggles to show more. */
const VIEW_LIMIT = 5 * 1024 * 1024

/** The open spoiler log, with a filter to find one item or location. */
function SpoilerViewer({ info, onClose }: { info: SpoilerInfo; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    getSpoilerText(controller.signal)
      .then(setText)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [])

  const shown = useMemo(() => {
    if (text === null || !filter) return text
    const needle = filter.toLowerCase()
    return text
      .split('\n')
      .filter((line) => line.toLowerCase().includes(needle))
      .join('\n')
  }, [text, filter])

  return (
    <Modal opened onClose={onClose} title={info.file} size="xl">
      <Stack gap="sm">
        <Group>
          <TextInput
            aria-label="Filter lines"
            placeholder="Show only lines containing…"
            value={filter}
            onChange={(e) => setFilter(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Anchor href={spoilerUrl} size="sm">
            <Group gap={4}>
              <IconDownload size={14} />
              Download
            </Group>
          </Anchor>
        </Group>
        {error && (
          <Alert color="red" title="Couldn't load the spoiler log">
            {error}
          </Alert>
        )}
        {text === null && !error && <Loader size="sm" />}
        {shown !== null && (
          <Code block mah="60vh" style={{ overflow: 'auto' }}>
            {shown || 'No matching lines'}
          </Code>
        )}
      </Stack>
    </Modal>
  )
}

/** The generated game's spoiler log (admin only). None of it is fetched until the admin
 * answers "Are you sure?": the admin may be playing in the game too. */
export function SpoilerLog() {
  const [info, setInfo] = useState<SpoilerInfo | null>(null)
  const [step, setStep] = useState<'closed' | 'confirm' | 'view'>('closed')

  useEffect(() => {
    const controller = new AbortController()
    getSpoiler(controller.signal)
      .then(setInfo)
      .catch(() => setInfo(null))
    return () => controller.abort()
  }, [])

  if (!info) return null
  const close = () => setStep('closed')
  return (
    <>
      <Group>
        <Button
          variant="subtle"
          color="red"
          size="xs"
          leftSection={<IconEyeOff size={14} />}
          onClick={() => setStep('confirm')}
        >
          Spoiler log
        </Button>
      </Group>
      <Modal opened={step === 'confirm'} onClose={close} title="Are you sure?">
        <Stack gap="sm">
          <Text size="sm">
            The spoiler log shows where every item is, in every player's world. If you're playing in
            this game, it will spoil it.
          </Text>
          {info.size > VIEW_LIMIT && (
            <Text size="sm" c="dimmed">
              It's {Math.ceil(info.size / (1024 * 1024))} MB, too large to show here; download it
              instead.
            </Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              Cancel
            </Button>
            <Button component="a" href={spoilerUrl} variant="light" color="red" onClick={close}>
              Yes, download it
            </Button>
            {info.size <= VIEW_LIMIT && (
              <Button color="red" onClick={() => setStep('view')}>
                Yes, show it
              </Button>
            )}
          </Group>
        </Stack>
      </Modal>
      {step === 'view' && <SpoilerViewer info={info} onClose={close} />}
    </>
  )
}
