"""Exercise hardware fades against a fake sysfs device and monotonic clock."""
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('backlight', Path(__file__).resolve().parents[1]/'panel-ui/backlight.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as folder:
    dev = Path(folder)/'brightness'
    power = Path(folder)/'bl_power'
    dev.write_text('0'); power.write_text('4')
    clock = [0.0]
    ramp = module.BrightnessRamp(clock=lambda: clock[0])
    ramp.request(str(dev), 255, 255, 1000)
    assert dev.read_text() == '0' and power.read_text() == '0'
    levels = []
    for i in range(1, 51):
        clock[0] = i*.02
        ramp.tick()
        levels.append(int(dev.read_text()))
    assert levels[-1] == 255 and all(0 < b-a <= 6 for a,b in zip([0]+levels, levels))
    ramp.request(str(dev), 255, 50, 1000)
    clock[0] = 1.5; ramp.tick()
    halfway = int(dev.read_text())
    assert 150 <= halfway <= 154
    ramp.request(str(dev), 255, 50, 1000)
    assert ramp.started == 1.0, 'repeat must not reset the fade'
    ramp.request(str(dev), 255, 230, 400)
    assert int(dev.read_text()) == halfway, 'retarget must not jump'
    clock[0] = 1.7; ramp.tick()
    assert halfway < int(dev.read_text()) < 230
    ramp.request(str(dev), 255, 0, 400)
    assert dev.read_text() == '0' and power.read_text() == '4'
    clock[0] = 20; ramp.tick()
    assert dev.read_text() == '0' and power.read_text() == '4', 'cancelled fade cannot wake screen'
    ramp.request(str(dev), 1023, 128, 400)
    clock[0] = 20.4; ramp.tick()
    assert int(dev.read_text()) == round(128/255*1023)
    power.write_text('4')
    ramp.request(str(dev), 1023, 128, 400)
    assert power.read_text() == '0' and dev.read_text() == '0'
    clock[0] = 21; ramp.tick()
    assert int(dev.read_text()) == round(128/255*1023)
    ramp.request(str(dev), 1023, 255, 0)
    assert dev.read_text() == '1023'
print('PASS backlight: fine hardware steps, retargeting, duplicate target, immediate blank, cancelled fade, wake, native range and instant compatibility')
