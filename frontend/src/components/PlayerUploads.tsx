import {
  Alert,
  Badge,
  Button,
  Card,
  FileButton,
  Group,
  MultiSelect,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconUpload } from '@tabler/icons-react'
import { useCallback, useEffect, useState } from 'react'
import {
  getPlayerLibrary,
  getPlayerUploads,
  loadReceipts,
  playerRename,
  playerUploadApworld,
  playerUploadYaml,
  playerWithdraw,
  saveReceipts,
  type PlayerGame,
  type PlayerLibrary,
  type PlayerUpload,
  type Receipt,
} from '../api/client'

const POLL_MS = 2000

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

const statusBadge: Record<string, { label: string; color: string }> = {
  pending: { label: 'checking', color: 'blue' },
  checking: { label: 'checking', color: 'blue' },
  'needs-name': { label: 'needs a name', color: 'orange' },
  accepted: { label: 'accepted', color: 'green' },
  approved: { label: 'approved', color: 'green' },
  rejected: { label: 'rejected', color: 'red' },
  removed: { label: 'withdrawn', color: 'gray' },
}

/** A YAML upload's status as the player sees it, and what they can do about it. */
function MyUpload({
  upload,
  receipt,
  open,
  onChanged,
}: {
  upload: PlayerUpload
  receipt: Receipt
  open: boolean
  onChanged: () => void
}) {
  const problems = upload.name_problems ?? []
  const [names, setNames] = useState<Record<number, string>>(() =>
    Object.fromEntries(problems.map((p) => [p.document, p.suggestion])),
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onChanged()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  const badge = statusBadge[upload.status] ?? { label: upload.status, color: 'gray' }
  const waiting = upload.kind === 'apworld' && upload.status === 'pending'
  return (
    <Card withBorder padding="sm">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" fw={500} truncate>
            {upload.kind === 'apworld' ? (upload.label ?? upload.filename) : upload.filename}
          </Text>
          <Badge color={badge.color} variant="light">
            {waiting ? 'waiting for the admin' : badge.label}
          </Badge>
        </Group>
        {upload.slots && upload.slots.length > 0 && (
          <Text size="sm" c="dimmed">
            Slots: {upload.slots.join(', ')}
          </Text>
        )}
        {upload.error_message && (
          <Text size="sm" c="red">
            {upload.error_message}
            {upload.error_code ? ` (${upload.error_code})` : ''}
          </Text>
        )}
        {waiting && (
          <Text size="sm" c="dimmed">
            It passed its checks. Once the admin approves it, pick it for your YAML.
          </Text>
        )}
        {upload.status === 'needs-name' && open && (
          <Stack gap={6}>
            {problems.map((p) => (
              <TextInput
                key={p.document}
                label={`New slot name${problems.length > 1 ? ` (document ${p.document + 1})` : ''}`}
                description={p.message}
                value={names[p.document] ?? ''}
                onChange={(e) => {
                  const value = e.currentTarget.value
                  setNames((old) => ({ ...old, [p.document]: value }))
                }}
                maxLength={16}
                maw={320}
              />
            ))}
            <Group>
              <Button
                size="xs"
                loading={busy}
                onClick={() =>
                  act(() =>
                    playerRename(
                      receipt,
                      problems.map((p) => ({
                        document: p.document,
                        name: names[p.document] ?? '',
                      })),
                    ),
                  )
                }
              >
                Use these names
              </Button>
            </Group>
          </Stack>
        )}
        {error && <Alert color="red">{error}</Alert>}
        {upload.kind === 'yaml' &&
          open &&
          (upload.status === 'accepted' || upload.status === 'needs-name') && (
            <Group>
              <Button
                size="xs"
                variant="subtle"
                color="red"
                loading={busy}
                onClick={() => act(() => playerWithdraw(receipt))}
              >
                Withdraw
              </Button>
            </Group>
          )}
      </Stack>
    </Card>
  )
}

/** Uploading for the game from the Player tab (#33), and the player's own uploads, found
 * by the receipts this browser keeps. */
export function PlayerUploads({ game }: { game: PlayerGame }) {
  const [receipts, setReceipts] = useState<Receipt[]>(loadReceipts)
  const [mine, setMine] = useState<PlayerUpload[]>([])
  const [library, setLibrary] = useState<PlayerLibrary | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    if (game.uploads_open)
      getPlayerLibrary(controller.signal)
        .then(setLibrary)
        .catch(() => undefined)
    if (receipts.length)
      getPlayerUploads(receipts)
        .then((found) => {
          if (!controller.signal.aborted) setMine(found)
        })
        .catch(() => undefined)
    return () => controller.abort()
  }, [receipts, version, game.uploads_open])

  const checking = mine.some((u) => u.status === 'pending' || u.status === 'checking')
  useEffect(() => {
    if (!checking) return
    const timer = setInterval(reload, POLL_MS)
    return () => clearInterval(timer)
  }, [checking, reload])

  const upload = async (send: () => Promise<{ receipt: string; upload: PlayerUpload }>) => {
    setBusy(true)
    setError(null)
    try {
      const { receipt, upload } = await send()
      const next = [...receipts, { kind: upload.kind, id: upload.id, receipt }]
      saveReceipts(next)
      setReceipts(next)
      setPicked([])
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  const receiptFor = (u: PlayerUpload) =>
    receipts.find((r) => r.kind === u.kind && r.id === u.id) as Receipt
  // This game's YAMLs, and any apworld still waiting or recent.
  const shown = mine
    .filter((u) => u.kind === 'apworld' || u.current_game)
    .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
  if (!game.uploads_open && shown.length === 0) return null

  return (
    <Stack>
      {game.uploads_open && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={3}>Join the game</Title>
            <Text size="sm">
              Upload your YAML. It's checked by Archipelago before it's accepted. {game.slots_used}{' '}
              of {game.max_slots} slots are taken.
            </Text>
            {game.taken_names.length > 0 && (
              <Text size="sm" c="dimmed">
                Taken slot names: {game.taken_names.join(', ')}
              </Text>
            )}
            {library && library.locked.length > 0 && (
              <Group gap={4}>
                <Text size="sm" c="dimmed">
                  World versions in use:
                </Text>
                {library.locked.map((l) => (
                  <Badge key={l.world} variant="outline">
                    {l.label}
                  </Badge>
                ))}
              </Group>
            )}
            {library && library.apworlds.length > 0 && (
              <MultiSelect
                label="Custom apworlds for your YAML"
                description="Only if your game needs one. Games you don't pick use the version in use, else the official world."
                placeholder="Official worlds"
                data={library.apworlds.map((a) => ({
                  value: String(a.id),
                  label: a.replaces_builtin ? `${a.label} (replaces the built-in)` : a.label,
                }))}
                value={picked}
                onChange={setPicked}
                clearable
                maw={520}
              />
            )}
            <Group>
              <FileButton
                onChange={(file) =>
                  file && upload(() => playerUploadYaml(file, picked.map(Number)))
                }
                accept=".yaml,.yml,text/yaml"
              >
                {(props) => (
                  <Button {...props} leftSection={<IconUpload size={16} />} loading={busy}>
                    Upload YAML
                  </Button>
                )}
              </FileButton>
              <FileButton
                onChange={(file) => file && upload(() => playerUploadApworld(file))}
                accept=".apworld"
              >
                {(props) => (
                  <Button {...props} variant="default" loading={busy}>
                    Upload an apworld
                  </Button>
                )}
              </FileButton>
            </Group>
            <Text size="xs" c="dimmed">
              Playing a game that isn't built into Archipelago? Upload its .apworld first.{' '}
              {game.apworld_approval === 'manual'
                ? 'The admin approves it after its checks, then you can pick it for your YAML.'
                : 'Once it passes its checks you can pick it for your YAML.'}
            </Text>
            {error && (
              <Alert color="red" title="Upload failed">
                {error}
              </Alert>
            )}
          </Stack>
        </Card>
      )}
      {shown.length > 0 && (
        <Stack gap="xs">
          <Text fw={500}>Your uploads</Text>
          {shown.map((u) => (
            <MyUpload
              key={`${u.kind}-${u.id}-${u.status}`}
              upload={u}
              receipt={receiptFor(u)}
              open={game.uploads_open}
              onChanged={reload}
            />
          ))}
          <Text size="xs" c="dimmed">
            This browser remembers your uploads. From another browser you won't see them here.
          </Text>
        </Stack>
      )}
    </Stack>
  )
}
