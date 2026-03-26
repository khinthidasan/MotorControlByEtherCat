import pysoem
import time


# -----------------------------
# EtherCAT Master Wrapper
# -----------------------------
class EtherCATMaster:
    def __init__(self, ifname):
        self.master = pysoem.Master()
        self.ifname = ifname

    def open(self):
        self.master.open(self.ifname)
        if self.master.config_init() <= 0:
            raise Exception("No slaves found")

    def config(self):
        self.master.config_map()
        self.master.state_check(pysoem.SAFEOP_STATE, 50000)

    def to_op(self):
        self.master.state = pysoem.OP_STATE
        self.master.write_state()

        # Send process data to reach OP
        for _ in range(100):
            self.master.send_processdata()
            self.master.receive_processdata()
            time.sleep(0.01)

        self.master.state_check(pysoem.OP_STATE, 50000)

    def close(self):
        self.master.state = pysoem.INIT_STATE
        self.master.write_state()
        self.master.close()


# -----------------------------
# Servo Drive (CiA402)
# -----------------------------
class ServoDrive:
    def __init__(self, slave):
        self.slave = slave

    # ---- Low-level ----
    def write_u16(self, index, subindex, value):
        self.slave.sdo_write(index, subindex, value.to_bytes(2, 'little'))

    def write_u32(self, index, subindex, value):
        self.slave.sdo_write(index, subindex, value.to_bytes(4, 'little', signed=True))

    def write_u8(self, index, subindex, value):
        self.slave.sdo_write(index, subindex, value.to_bytes(1, 'little'))

    def read_u16(self, index, subindex):
        return int.from_bytes(self.slave.sdo_read(index, subindex), 'little')

    # ---- CiA402 helpers ----
    def set_mode(self, mode):
        self.write_u8(0x6060, 0, mode)

    def controlword(self, value):
        self.write_u16(0x6040, 0, value)

    def statusword(self):
        return self.read_u16(0x6041, 0)

    def wait_status(self, target, mask=0x006F, timeout=2.0):
        start = time.time()
        while time.time() - start < timeout:
            if (self.statusword() & mask) == target:
                return True
            time.sleep(0.01)
        return False

    # ---- High-level API ----
    def reset_fault(self):
        self.controlword(0x0080)
        time.sleep(0.1)

    def enable(self):
        # Set mode (Profile Position)
        self.set_mode(1)

        self.reset_fault()

        # Shutdown
        self.controlword(0x0006)
        if not self.wait_status(0x0021):
            raise Exception("Shutdown failed")

        # Switch ON
        self.controlword(0x0007)
        if not self.wait_status(0x0023):
            raise Exception("Switch ON failed")

        # Enable Operation
        self.controlword(0x000F)
        if not self.wait_status(0x0027):
            raise Exception("Enable failed")

        print("Servo ENABLED")

    def move_to(self, position):
        # Target position
        self.write_u32(0x607A, 0, position)

        # Trigger motion
        self.controlword(0x003F)

    def get_position(self):
        return int.from_bytes(
            self.slave.sdo_read(0x6064, 0),
            'little',
            signed=True
        )

# -----------------------------
# IO Class
# -----------------------------
class DigitalIO:
    def __init__(self, slave):
        self.slave = slave
        self.output_value = 0

    def read_all(self):
        return int.from_bytes(self.slave.input, 'little')

    def read_bit(self, ch):
        value = self.read_all()
        return (value >> ch) & 1

    def set_bit(self, ch, state):
        if state:
            self.output_value |= (1 << ch)
        else:
            self.output_value &= ~(1 << ch)

        self.slave.output = self.output_value.to_bytes(1, 'little')


# -----------------------------
# Application
# -----------------------------
class MotionApp:
    def __init__(self, ifname):
        self.master = EtherCATMaster(ifname)
        self.servo = None
        self.io = None

    def start(self):
        self.master.open()
        self.master.config()
        self.master.to_op()

        slave = self.master.master.slaves[0]
        self.servo = ServoDrive(slave)

        self.io = DigitalIO(self.master.master.slaves[1])

        print("System ready")

    def run(self):
        self.servo.enable()

        # Move example
        self.servo.move_to(20000)
        time.sleep(2)

        # Turn ON DO0
        self.io.set_bit(0, 1)

        # Turn ON DO1
        self.io.set_bit(1, 1)



    def loop(self):
        try:
            while True:
                self.master.master.send_processdata()
                self.master.master.receive_processdata()
                


                di0 = self.io.read_bit(0)
                di1 = self.io.read_bit(1)

                print(f"DI0={di0}, DI1={di1}")
                time.sleep(1)

        except KeyboardInterrupt:
            pass

    def stop(self):
        self.master.close()


# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    app = MotionApp(r'\Device\NPF_' +"{5EE58A83-DC64-4647-963D-8D7997E89D44}")  # Window
    # app = MotionApp("eth0")  # Linux


    try:
        app.start()
        app.run()
        app.loop()
    finally:
        app.stop()