import { Alert, Badge, Button, Code, Group, Loader, Modal, Stack, Table, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import {
  approveApworld,
  getApworld,
  rejectApworld,
  type Apworld,
  type ApworldDetail,
} from '../api/client'

interface Props {
  apworld: Apworld
  onClose: () => void
  onDone: () => void
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Table.Tr>
      <Table.Th w={160}>{label}</Table.Th>
      <Table.Td>{children}</Table.Td>
    </Table.Tr>
  )
}

/** The approval screen (DESIGN.md §4): manifest, file list, hash, uploader and the
 * worker's import test, with Approve / Reject while the apworld is pending. */
export function ReviewApworldModal({ apworld, onClose, onDone }: Props) {
  const [detail, setDetail] = useState<ApworldDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getApworld(apworld.id, controller.signal)
      .then(setDetail)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [apworld.id])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const test = detail?.import_test
  return (
    <Modal opened onClose={onClose} title={apworld.label} size="lg">
      {!detail ? (
        error ? (
          <Alert color="red">{error}</Alert>
        ) : (
          <Loader size="sm" />
        )
      ) : (
        <Stack>
          {detail.replaces_builtin && (
            <Alert color="orange" icon={<IconAlertTriangle />} title="Replaces a built-in world">
              {detail.game} is built into Archipelago (version {detail.replaces_builtin}). Approving
              this puts a custom version of it in the library. It always needs your approval.
            </Alert>
          )}
          <Table verticalSpacing={4}>
            <Table.Tbody>
              <Field label="Game">{detail.game}</Field>
              <Field label="World version">{detail.world_version ?? 'not given'}</Field>
              <Field label="Archipelago">
                {detail.minimum_ap_version ?? 'any'} to {detail.maximum_ap_version ?? 'any'}
              </Field>
              <Field label="Authors">{detail.authors.join(', ') || 'not given'}</Field>
              <Field label="File">
                {detail.filename} ({Math.ceil(detail.size / 1024)} KB)
              </Field>
              <Field label="SHA-256">
                <Code style={{ wordBreak: 'break-all' }}>{detail.sha256}</Code>
              </Field>
              <Field label="Uploaded by">
                {detail.uploaded_by}, {new Date(detail.uploaded_at).toLocaleString()}
              </Field>
              <Field label="Import test">
                {!test ? (
                  <Text size="sm" c="dimmed">
                    {detail.status === 'checking' ? 'running' : 'not run'}
                  </Text>
                ) : test.loaded ? (
                  <Badge color="green" variant="light">
                    loaded: {test.games.join(', ')}
                  </Badge>
                ) : (
                  <Text size="sm" c="red">
                    {test.error}
                  </Text>
                )}
              </Field>
            </Table.Tbody>
          </Table>
          {test?.detail && (
            <Code block mah={200} style={{ overflow: 'auto' }}>
              {test.detail}
            </Code>
          )}
          <Text fw={500} size="sm">
            Files ({detail.files.length})
          </Text>
          <Code block mah={160} style={{ overflow: 'auto' }}>
            {detail.files.map((f) => `${f.name}  ${f.size}`).join('\n')}
          </Code>
          {detail.manifest && (
            <>
              <Text fw={500} size="sm">
                archipelago.json
              </Text>
              <Code block>{JSON.stringify(detail.manifest, null, 2)}</Code>
            </>
          )}
          {error && <Alert color="red">{error}</Alert>}
          {detail.status === 'pending' && (
            <Group justify="flex-end">
              <Button
                variant="subtle"
                color="red"
                loading={busy}
                onClick={() => run(() => rejectApworld(detail.id))}
              >
                Reject
              </Button>
              <Button loading={busy} onClick={() => run(() => approveApworld(detail.id))}>
                Approve
              </Button>
            </Group>
          )}
        </Stack>
      )}
    </Modal>
  )
}
