import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconBolt, IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import {
  getSettings,
  putSettings,
  type SettingField,
  type SettingValue,
  type SettingsPage as Page,
} from '../api/client'

const groups: { key: SettingField['group']; title: string; note: string }[] = [
  {
    key: 'server',
    title: 'Server',
    note: 'Applied at every start. Those marked live also change a running server at once.',
  },
  { key: 'generation', title: 'Generation', note: 'Applied at the next generation.' },
  { key: 'uploads', title: 'Uploads', note: 'Applied to the next upload.' },
  {
    key: 'archives',
    title: 'Archives',
    note: 'Applied each time a game is archived; saving here deletes nothing.',
  },
  { key: 'advanced', title: 'Advanced', note: '' },
]

const appliesBadge: Record<SettingField['applies'], string> = {
  live: 'Live',
  start: 'Next start',
  generation: 'Next generation',
  upload: 'Next upload',
  archive: 'Next archive',
}

interface FieldProps {
  field: SettingField
  value: SettingValue
  onChange: (value: SettingValue) => void
}

function FieldInput({ field, value, onChange }: FieldProps) {
  const label = (
    <Group gap={6} wrap="nowrap" component="span">
      {field.label}
      <Badge
        size="xs"
        variant="light"
        color={field.applies === 'live' ? 'grape' : 'gray'}
        leftSection={field.applies === 'live' ? <IconBolt size={10} /> : undefined}
      >
        {appliesBadge[field.applies]}
      </Badge>
    </Group>
  )
  const description =
    field.warning && field.kind !== 'choice' ? `${field.help} ${field.warning}` : field.help
  switch (field.kind) {
    case 'bool':
      return (
        <Switch
          label={label}
          description={description}
          checked={Boolean(value)}
          onChange={(e) => onChange(e.currentTarget.checked)}
          color={field.warning && value ? 'orange' : undefined}
        />
      )
    case 'number':
      return (
        <NumberInput
          label={label}
          description={description}
          value={Number(value)}
          onChange={(v) => onChange(typeof v === 'number' ? v : Number(v) || 0)}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          allowDecimal={false}
          maw={320}
        />
      )
    case 'choice': {
      // A warning is about leaving the first (safe) choice: shown when another is picked.
      const risky = field.warning !== null && value !== field.choices[0]?.value
      return (
        <Stack gap={6}>
          <Select
            label={label}
            description={description}
            data={field.choices.map((c) => ({ value: String(c.value), label: c.label }))}
            value={String(value)}
            onChange={(v) => {
              const choice = field.choices.find((c) => String(c.value) === v)
              if (choice) onChange(choice.value)
            }}
            allowDeselect={false}
            maw={420}
          />
          {risky && (
            <Alert color="orange" maw={560} py={6}>
              {field.warning}
            </Alert>
          )}
        </Stack>
      )
    }
    case 'multi':
      return (
        <Checkbox.Group
          label={label}
          description={description}
          value={value as string[]}
          onChange={onChange}
        >
          <Group mt={6}>
            {field.choices.map((c) => (
              <Checkbox key={String(c.value)} value={String(c.value)} label={c.label} />
            ))}
          </Group>
        </Checkbox.Group>
      )
    case 'password':
      return (
        <PasswordInput
          label={label}
          description={description}
          value={String(value)}
          onChange={(e) => onChange(e.currentTarget.value)}
          maxLength={64}
          maw={320}
        />
      )
    default:
      return (
        <TextInput
          label={label}
          description={description}
          value={String(value)}
          onChange={(e) => onChange(e.currentTarget.value)}
          maw={320}
        />
      )
  }
}

/** The host.yaml settings (DESIGN.md §5): the server's, generation's and uploads'. */
export function SettingsPage() {
  const [page, setPage] = useState<Page | null>(null)
  const [values, setValues] = useState<Record<string, SettingValue>>({})
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [advanced, setAdvanced] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getSettings(controller.signal)
      .then((p) => {
        setPage(p)
        setValues(p.values)
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [])

  const save = async () => {
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      const result = await putSettings(values)
      setValues(result.values)
      setSaved(result.applied_now)
      setPage((p) => (p ? { ...p, reset: [] } : p))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const label = (key: string) => page?.fields.find((f) => f.key === key)?.label ?? key
  return (
    <Stack maw={960}>
      <Title order={2}>Settings</Title>
      {!page && !error && <Loader size="sm" />}
      {page && page.reset.length > 0 && (
        <Alert color="orange" title="Some settings were reset after an update">
          These stored settings no longer fit this version and are back at their defaults:{' '}
          {page.reset.map(label).join(', ')}. Check them, then save.
        </Alert>
      )}
      {page &&
        groups.map((group) => {
          const fields = page.fields.filter((f) => f.group === group.key)
          const open = group.key !== 'advanced' || advanced
          return (
            <Card withBorder key={group.key}>
              <Stack gap="md">
                {group.key === 'advanced' ? (
                  <Button
                    variant="subtle"
                    color="gray"
                    justify="flex-start"
                    px={0}
                    leftSection={
                      advanced ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />
                    }
                    onClick={() => setAdvanced((a) => !a)}
                  >
                    {group.title}
                  </Button>
                ) : (
                  <Stack gap={2}>
                    <Text fw={500}>{group.title}</Text>
                    <Text size="sm" c="dimmed">
                      {group.note}
                    </Text>
                  </Stack>
                )}
                {open && (
                  <Stack gap="md">
                    {fields.map((field) => (
                      <FieldInput
                        key={field.key}
                        field={field}
                        value={values[field.key]}
                        onChange={(v) => setValues((old) => ({ ...old, [field.key]: v }))}
                      />
                    ))}
                  </Stack>
                )}
              </Stack>
            </Card>
          )
        })}
      {error && (
        <Alert color="red" title="Not saved">
          {error}
        </Alert>
      )}
      {saved && (
        <Alert color="green" title="Saved">
          {saved.length > 0
            ? `Applied to the running server now: ${saved.map(label).join(', ')}. `
            : ''}
          Everything else applies at the next start, generation, upload or archive.
        </Alert>
      )}
      {page && (
        <Group>
          <Button onClick={save} loading={busy}>
            Save settings
          </Button>
        </Group>
      )}
    </Stack>
  )
}
