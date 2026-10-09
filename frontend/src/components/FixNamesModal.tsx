import { Alert, Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core'
import { useState } from 'react'
import { cancelUpload, renameUpload, type NameProblem, type Upload } from '../api/client'

function describe(current: NameProblem['current']): string {
  if (current === null) return 'no name'
  if (Array.isArray(current)) return `one of ${current.join(', ')}`
  return current
}

interface Props {
  upload: Upload
  onClose: () => void
  onDone: () => void
}

/** An upload whose slot names need changing: rename on the spot (the service edits the
 * YAML), or cancel, which rejects it so a fixed file has to be uploaded. */
export function FixNamesModal({ upload, onClose, onDone }: Props) {
  const [names, setNames] = useState<Record<number, string>>(() =>
    Object.fromEntries(upload.name_problems.map((p) => [p.document, p.suggestion])),
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)

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

  const save = () =>
    run(() =>
      renameUpload(
        upload.id,
        upload.name_problems.map((p) => ({ document: p.document, name: names[p.document] ?? '' })),
      ),
    )

  return (
    <Modal opened onClose={onClose} title={`Slot names in ${upload.filename}`}>
      <Stack>
        <Text size="sm">
          Choose a new name and the file is updated for you, or cancel to reject it so a fixed file
          can be uploaded instead.
        </Text>
        {upload.name_problems.map((p) => (
          <TextInput
            key={p.document}
            label={`Slot ${p.document + 1}: ${describe(p.current)}`}
            description={p.message}
            maxLength={16}
            value={names[p.document] ?? ''}
            onChange={(e) => setNames({ ...names, [p.document]: e.currentTarget.value })}
          />
        ))}
        {error && (
          <Alert color="red" title="Not saved">
            {error}
          </Alert>
        )}
        {confirmCancel ? (
          <Alert color="red" title="Cancel this upload?">
            <Stack gap="xs">
              <Text size="sm">
                The file will be rejected. A fixed file will have to be uploaded.
              </Text>
              <Group>
                <Button
                  color="red"
                  loading={busy}
                  onClick={() => run(() => cancelUpload(upload.id))}
                >
                  Yes, cancel upload
                </Button>
                <Button variant="default" onClick={() => setConfirmCancel(false)}>
                  Keep it
                </Button>
              </Group>
            </Stack>
          </Alert>
        ) : (
          <Group justify="space-between">
            <Button variant="subtle" color="red" onClick={() => setConfirmCancel(true)}>
              Cancel upload
            </Button>
            <Button loading={busy} onClick={save}>
              Save names
            </Button>
          </Group>
        )}
      </Stack>
    </Modal>
  )
}
