
```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
```


## List All IDs

```bash
.venv/bin/python test_results/test_runner.py --list
```

## Unit Testing

```bash
.venv/bin/python test_results/test_runner.py --id UT-1
.venv/bin/python test_results/test_runner.py --id UT-2
.venv/bin/python test_results/test_runner.py --id UT-3
.venv/bin/python test_results/test_runner.py --id UT-4
```

## Integration Testing

```bash
.venv/bin/python test_results/test_runner.py --id IT-1
.venv/bin/python test_results/test_runner.py --id IT-2
.venv/bin/python test_results/test_runner.py --id IT-3
```

## System Testing

```bash
.venv/bin/python test_results/test_runner.py --id ST-1
.venv/bin/python test_results/test_runner.py --id ST-2
.venv/bin/python test_results/test_runner.py --id ST-3
```

## Performance Testing

```bash
.venv/bin/python test_results/test_runner.py --id PT-1
.venv/bin/python test_results/test_runner.py --id PT-2
```

## Recovery Testing

```bash
.venv/bin/python test_results/test_runner.py --id RT-1
.venv/bin/python test_results/test_runner.py --id RT-2
```

## Security Testing

```bash
.venv/bin/python test_results/test_runner.py --id SCT-1
.venv/bin/python test_results/test_runner.py --id SCT-2
.venv/bin/python test_results/test_runner.py --id SCT-3
```
