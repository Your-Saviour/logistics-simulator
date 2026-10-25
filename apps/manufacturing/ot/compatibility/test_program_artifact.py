import tempfile
from pathlib import Path
import unittest
from program_artifact import record, verify


class ProgramArtifactTest(unittest.TestCase):
    def test_recorded_program_survives_restart_and_rejects_source_or_binary_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, build = root / 'source', root / 'build'
            source.mkdir(); build.mkdir()
            (source / 'program.st').write_text('PROGRAM Cell END_PROGRAM')
            self.assertFalse(verify(source, build))
            (build / 'libplc_1.so').write_bytes(b'compiled-program')
            with self.assertRaises(RuntimeError):
                verify(source, build)
            record(source, build)
            self.assertTrue(verify(source, build))
            (source / 'program.st').write_text('different program')
            with self.assertRaises(RuntimeError):
                verify(source, build)
            (source / 'program.st').write_text('PROGRAM Cell END_PROGRAM')
            (build / 'libplc_1.so').write_bytes(b'foreign program')
            with self.assertRaises(RuntimeError):
                verify(source, build)


if __name__ == '__main__':
    unittest.main()
