import { Alert, Button, Group, Modal, Select, Stack, Text } from '@mantine/core'
import { useState } from 'react'
import { overrideWorld, type Apworld, type WorldLock } from '../api/client'

const OFFICIAL = 'official'

interface Props {
  lock: WorldLock
  library: Apworld[]
  /** Accepted YAMLs (and ones waiting for a name) that use this game. */
  affected: number
  onClose: () => void
  onDone: () => void
}

/** The admin changes the version a game is locked to (#34). Every YAML using it is
 * checked again with the new one; the ones that fail have to be uploaded again. */
export function OverrideVersionModal({ lock, library, affected, onClose, onDone }: Props) {
  const choices = [
    { value: OFFICIAL, label: `${lock.world} · official (built in)` },
    ...library
      .filter((a) => a.game === lock.world)
      .map((a) => ({ value: String(a.id), label: a.label })),
  ].filter((c) => c.value !== (lock.apworld_id === null ? OFFICIAL : String(lock.apworld_id)))
  const [picked, setPicked] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    if (!picked) return
    setBusy(true)
    setError(null)
    try {
      await overrideWorld(lock.world, picked === OFFICIAL ? null : Number(picked))
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal opened onClose={onClose} title={`Change the version of ${lock.world}`}>
      <Stack gap="sm">
        <Text size="sm">Now: {lock.label}</Text>
        <Select
          label="New version"
          placeholder="Pick a version"
          data={choices}
          value={picked}
          onChange={setPicked}
          allowDeselect={false}
        />
        <Alert color="yellow">
          {affected === 1 ? '1 YAML uses' : `${affected} YAMLs use`} {lock.world}. Each is checked
          again with the new version straight away; any that fail are rejected and listed here, and
          those players have to upload again.
        </Alert>
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={!picked}>
            Change and re-check
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
