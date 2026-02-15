"""Single DC motor driver via L293D on Raspberry Pi GPIO.

Uses half-bridge A (pins 1-8 on L293D):
  - GPIO12 (PWM0) → L293D pin 1 (1-2EN) — speed control
  - GPIO5        → L293D pin 2 (1A)    — direction input 1
  - GPIO6        → L293D pin 7 (2A)    — direction input 2
"""

import logging
import time

log = logging.getLogger("sdr.motor")

# Default GPIO assignments (matching Raspberry.MD)
PIN_EN = 12   # PWM enable (speed)
PIN_1A = 5    # direction input 1
PIN_2A = 6    # direction input 2

PWM_FREQ = 1000  # Hz

_gpio = None
_pwm = None


def _init_gpio():
    global _gpio, _pwm
    if _gpio is not None:
        return True
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(PIN_EN, GPIO.OUT)
        GPIO.setup(PIN_1A, GPIO.OUT)
        GPIO.setup(PIN_2A, GPIO.OUT)
        _pwm = GPIO.PWM(PIN_EN, PWM_FREQ)
        _pwm.start(0)
        _gpio = GPIO
        log.info("Motor GPIO initialized: EN=%d, 1A=%d, 2A=%d", PIN_EN, PIN_1A, PIN_2A)
        return True
    except Exception as e:
        log.warning("Motor GPIO init failed: %s", e)
        return False


def forward(speed: int = 100):
    """Run motor forward at given speed (0-100%)."""
    if not _init_gpio():
        log.info("[SIM] Motor forward %d%%", speed)
        return
    _gpio.output(PIN_1A, _gpio.HIGH)
    _gpio.output(PIN_2A, _gpio.LOW)
    _pwm.ChangeDutyCycle(speed)
    log.debug("Motor forward %d%%", speed)


def reverse(speed: int = 100):
    """Run motor reverse at given speed (0-100%)."""
    if not _init_gpio():
        log.info("[SIM] Motor reverse %d%%", speed)
        return
    _gpio.output(PIN_1A, _gpio.LOW)
    _gpio.output(PIN_2A, _gpio.HIGH)
    _pwm.ChangeDutyCycle(speed)
    log.debug("Motor reverse %d%%", speed)


def stop():
    """Stop motor (coast)."""
    if not _init_gpio():
        log.info("[SIM] Motor stop")
        return
    _gpio.output(PIN_1A, _gpio.LOW)
    _gpio.output(PIN_2A, _gpio.LOW)
    _pwm.ChangeDutyCycle(0)
    log.debug("Motor stop")


def brake():
    """Brake motor (active stop)."""
    if not _init_gpio():
        log.info("[SIM] Motor brake")
        return
    _gpio.output(PIN_1A, _gpio.HIGH)
    _gpio.output(PIN_2A, _gpio.HIGH)
    _pwm.ChangeDutyCycle(100)
    log.debug("Motor brake")


def cleanup():
    """Release GPIO resources."""
    global _gpio, _pwm
    if _pwm:
        _pwm.stop()
        _pwm = None
    if _gpio:
        _gpio.cleanup([PIN_EN, PIN_1A, PIN_2A])
        _gpio = None
    log.info("Motor GPIO cleanup")


def test_cycle(duration: float = 5.0, speed: int = 50):
    """Test motor: forward for duration/2, reverse for duration/2, then stop."""
    half = duration / 2.0
    log.info("Motor test: forward %ds at %d%%", half, speed)
    forward(speed)
    time.sleep(half)
    log.info("Motor test: reverse %ds at %d%%", half, speed)
    reverse(speed)
    time.sleep(half)
    stop()
    log.info("Motor test complete")
