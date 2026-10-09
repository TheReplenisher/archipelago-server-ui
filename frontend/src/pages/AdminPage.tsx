import { Alert, Stack, Text, Title } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { BackendStatus } from '../components/BackendStatus'
import { CurrentGame } from '../components/CurrentGame'
import { Uploads } from '../components/Uploads'

export function AdminPage() {
  return (
    <Stack maw={960}>
      <Title order={2}>Admin</Title>
      <Alert color="yellow" icon={<IconAlertTriangle />} title="No admin login in Alpha 1">
        Anyone who can reach this page can manage the server. Do not expose an Alpha 1 install to
        the internet.
      </Alert>
      <CurrentGame />
      <Uploads />
      <BackendStatus />
      <Text c="dimmed">
        Generation, the console and settings will appear here as Alpha 1 is built.
      </Text>
    </Stack>
  )
}
