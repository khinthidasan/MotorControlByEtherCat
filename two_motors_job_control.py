import time

import pysoem

WINDOWS_GUID = "{5EE58A83-DC64-4647-963D-8D7997E89D44}"
IFNAME_LINUX = "eth3"

# EtherCAT slave order:
# - slave0 => master.slaves[0]
# - slave1 => master.slaves[1]
SLAVE_IDX_0 = 0
SLAVE_IDX_1 = 1

# CiA402 / drive settings
OP_MODE_PROFILE_POSITION = 1  # 0x6060

# Ezi-Servo / CiA402 recommended motion parameters
DEFAULT_VELOCITY = 3000
DEFAULT_ACCEL = 1000
DEFAULT_DECEL = 1000


class EtherCATMaster:
    def __init__(self, ifname: str):
        self.master = pysoem.Master()
        self.ifname = ifname

    def open(self):
        self.master.open(self.ifname)
        if self.master.config_init() <= 0:
            raise RuntimeError("No slaves found")

    def config_and_to_op(self):
        self.master.config_map()
        self.master.state = pysoem.OP_STATE
        self.master.write_state()

        # Pump process data to help the drives reach OP state reliably.
        for _ in range(100):
            self.master.send_processdata()
            self.master.receive_processdata()
            time.sleep(0.01)

        self.master.state_check(pysoem.OP_STATE, 50000)

    def close(self):
        self.master.state = pysoem.INIT_STATE
        self.master.write_state()
        self.master.close()


class ServoDrive:
    # 0x6064: position actual value
    POS_ACTUAL = 0x6064
    # 0x607A: target position
    POS_TARGET = 0x607A
    # 0x6040: controlword
    CW = 0x6040
    # 0x6041: statusword
    SW = 0x6041
    # 0x6060: mode of operation
    MODE = 0x6060

    # Motion params
    VEL = 0x6081
    ACC = 0x6083
    DEC = 0x6084

    def __init__(self, slave, name: str):
        self.slave = slave
        self.name = name

    def _write_sdo(self, index: int, subindex: int, value: int, byte_len: int, *, signed: bool):
        self.slave.sdo_write(index, subindex, value.to_bytes(byte_len, "little", signed=signed))

    def _read_sdo(self, index: int, subindex: int, byte_len: int, *, signed: bool) -> int:
        data = self.slave.sdo_read(index, subindex)
        return int.from_bytes(data, "little", signed=signed)

    def write_u8(self, index, subindex, value):
        self._write_sdo(index, subindex, value, 1, signed=False)

    def write_u16(self, index, subindex, value):
        self._write_sdo(index, subindex, value, 2, signed=False)

    def write_u32(self, index, subindex, value):
        self._write_sdo(index, subindex, value, 4, signed=False)

    def write_i32(self, index, subindex, value):
        self._write_sdo(index, subindex, value, 4, signed=True)

    def read_u16(self, index, subindex) -> int:
        return self._read_sdo(index, subindex, 2, signed=False)

    def read_i32(self, index, subindex) -> int:
        return self._read_sdo(index, subindex, 4, signed=True)

    def controlword(self, value: int):
        # 0x6040: UINT16
        self.write_u16(self.CW, 0, value)

    def statusword(self) -> int:
        return self.read_u16(self.SW, 0)

    def set_mode_profile_position(self):
        # 0x6060: mode of operation
        self.write_u8(self.MODE, 0, OP_MODE_PROFILE_POSITION)

    def reset_fault(self):
        # Fault reset = bit7 in standard CiA402 controlword.
        self.controlword(0x0080)
        time.sleep(0.1)

    def enable_profile_position(self):
        self.set_mode_profile_position()
        self.reset_fault()

        # Shutdown
        self.controlword(0x0006)
        if not self._wait_status(0x0021):
            raise RuntimeError(f"{self.name}: Shutdown failed")

        # Switch on
        self.controlword(0x0007)
        if not self._wait_status(0x0023):
            raise RuntimeError(f"{self.name}: Switch ON failed")

        # Enable operation
        self.controlword(0x000F)
        if not self._wait_status(0x0027):
            raise RuntimeError(f"{self.name}: Enable operation failed")

        print(f"{self.name}: ENABLED")

    def _wait_status(self, target: int, mask: int = 0x006F, timeout: float = 2.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if (self.statusword() & mask) == target:
                return True
            time.sleep(0.01)
        return False

    def set_motion_parameters(self, *, velocity: int, acceleration: int, deceleration: int):
        #  CiA402 profile
        self.write_u32(self.VEL, 0, velocity)
        self.write_u32(self.ACC, 0, acceleration)
        self.write_u32(self.DEC, 0, deceleration)

    def get_position(self) -> int:
        return self.read_i32(self.POS_ACTUAL, 0)

    def write_target_position(self, position: int):
        # 0x607A is typically INT32 in CiA402 (signed).
        self.write_i32(self.POS_TARGET, 0, position)

    def trigger_absolute_motion(self):

        # - controlword 0x003F triggers motion in profile position mode
        # - then clear with 0x000F
        self.controlword(0x003F)
        time.sleep(0.01)
        self.controlword(0x000F)

    def halt(self):
        # Halt bit is bit8 in standard CiA402 controlword.
        # Using 0x010F (bit8=1 + enable operation bits) to command a halt,
        # then clearing with 0x000F.
        self.controlword(0x010F)
        time.sleep(0.01)
        self.controlword(0x000F)


def main():
    try:
        import msvcrt  # type: ignore
    except Exception:
        msvcrt = None

    # Windows uses GUID-style interface; on Linux use IFNAME_LINUX.
    # edit `WINDOWS_GUID` / `IFNAME_LINUX`.
    if_windows = True
    ifname = r"\Device\NPF_" + WINDOWS_GUID if if_windows else IFNAME_LINUX

    print("Connecting EtherCAT...")
    master = EtherCATMaster(ifname)
    master.open()
    master.config_and_to_op()

    try:
        s0 = master.master.slaves[SLAVE_IDX_0]
        s1 = master.master.slaves[SLAVE_IDX_1]

        drive0 = ServoDrive(s0, "slave0")
        drive1 = ServoDrive(s1, "slave1")

        drive0.set_motion_parameters(
            velocity=DEFAULT_VELOCITY,
            acceleration=DEFAULT_ACCEL,
            deceleration=DEFAULT_DECEL,
        )
        drive1.set_motion_parameters(
            velocity=DEFAULT_VELOCITY,
            acceleration=DEFAULT_ACCEL,
            deceleration=DEFAULT_DECEL,
        )

        drive0.enable_profile_position()
        drive1.enable_profile_position()

        print("Jog control ready.")
        print("Keys: '1' jog+ (both) | '2' jog- (both) | '3' s0 CW / s1 CCW | '4' s0 CCW / s1 CW | '0' stop | 'q' quit")

        # Direction per slave:
        # +1 => "jog+" (CW for slave0 in your setup)
        # -1 => "jog-" (CCW for slave0 in your setup)
        jog_dir0 = 0
        jog_dir1 = 0
        step_counts = 2000  # counts per jog step (tune for your mechanism)
        step_period_s = 0.05
        next_step_t = 0.0

        last_key_t = 0.0
        while True:
            # Keep EtherCAT process data flowing (helps with watchdog/timeouts).
            master.master.send_processdata()
            master.master.receive_processdata()

            # Handle keyboard.
            if msvcrt is not None and msvcrt.kbhit():
                raw = msvcrt.getch()
                try:
                    ch = raw.decode("ascii").strip().lower()
                except Exception:
                    ch = ""

                # Simple, non-blocking control:
                # - 1 sets both directions to +1
                # - 2 sets both directions to -1
                # - 3 sets slave0=+1, slave1=-1
                # - 4 sets slave0=-1, slave1=+1
                # - 0 stops both
                # - q quits
                if ch == "1":
                    jog_dir0 = 1
                    jog_dir1 = 1
                    last_key_t = time.time()
                elif ch == "2":
                    jog_dir0 = -1
                    jog_dir1 = -1
                    last_key_t = time.time()
                elif ch == "3":
                    jog_dir0 = 1
                    jog_dir1 = -1
                    last_key_t = time.time()
                elif ch == "4":
                    jog_dir0 = -1
                    jog_dir1 = 1
                    last_key_t = time.time()
                elif ch == "0":
                    jog_dir0 = 0
                    jog_dir1 = 0
                    drive0.halt()
                    drive1.halt()
                elif ch == "q":
                    break

            now = time.time()
            if (jog_dir0 != 0 or jog_dir1 != 0) and now >= next_step_t:
                # Compute targets from the current position to make steps robust.
                pos0 = drive0.get_position()
                pos1 = drive1.get_position()

                did0 = False
                did1 = False
                if jog_dir0 != 0:
                    drive0.write_target_position(pos0 + jog_dir0 * step_counts)
                    did0 = True
                if jog_dir1 != 0:
                    drive1.write_target_position(pos1 + jog_dir1 * step_counts)
                    did1 = True

                # Trigger only the drives that are jogging.
                if did0:
                    drive0.trigger_absolute_motion()
                if did1:
                    drive1.trigger_absolute_motion()

                next_step_t = now + step_period_s

            # Small sleep to reduce CPU usage without slowing EtherCAT updates too much.
            time.sleep(0.002)

    finally:
        print("Stopping EtherCAT...")
        master.close()


if __name__ == "__main__":
    main()

