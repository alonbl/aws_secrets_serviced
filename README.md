# aws_secrets_serviced

A systemd service to obtain secrets as an sysfs filesystem.

## Usage

```
usage: aws-secrets-serviced [-h] [--version] [--log-level LEVEL] [--log-file FILE] --config FILE

AWS secrets for services

options:
  -h, --help         show this help message and exit
  --version          show program's version number and exit
  --log-level LEVEL  Log level CRITICAL, ERROR, WARNING, INFO, DEBUG
  --log-file FILE    Log file to use, default is stdout
  --config FILE      Configuration file, may be specified multiple times
```

## Configuration File

```ini
[main]
mountpoint = /tmp/mm1
secrets = secret1, secret2

[secret1]
region = us-east-1
secret = secret1
dest = secret/destination/inside/mountpoint/secret1
owner = user1:user1
mode = 0600

[secret2]
region = us-east-1
secret = secret2
dest = secret/destination/inside/mountpoint/secret2
owner = user2:user2
mode = 0600
```

### Systemd Configuration

### /etc/default/aws-secrets-serviced

```sh
ARGS=--config=/etc/aws-secrets-serviced/main.conf
```

### /etc/systemd/system/\*.service.d/aws-secrets-serviced-order.conf

Per each service that requires secrets.

```ini
[Unit]
After=aws-secrets-serviced.service
Requires=aws-secrets-serviced.service
```
