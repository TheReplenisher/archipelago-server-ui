import { Alert, Stack, Text, Title } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { BackendStatus } from '../components/BackendStatus'

export function AdminPage() {
  return (
    <Stack maw={960}>
      <Title order={2}>Admin</Title>
      <Alert color="yellow" icon={<IconAlertTriangle />} title="No admin login in Alpha 1">
        Anyone who can reach this page can manage the server. Do not expose an Alpha 1 install to
        the internet.
      </Alert>
      <BackendStatus />
      <Text c="dimmed">
        Game lifecycle, uploads, console and settings will appear here as Alpha 1 is built.
      </Text>
    </Stack>
  )
}
