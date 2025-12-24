"""openWakeWord implementation."""

import ctypes as C
from collections.abc import Iterable
from pathlib import Path
from typing import Final, Optional, Union

import numpy as np

from .const import Model
from .wakeword import TfLiteWakeWord, get_platform

_DIR = Path(__file__).parent
_REPO_DIR = _DIR.parent
_MODULE_LIB_DIR = _DIR / "lib"
_REPO_LIB_DIR = _REPO_DIR / "lib"
_MODELS_DIR = _DIR / "models"

c_void_p = C.c_void_p
c_int32 = C.c_int32
c_size_t = C.c_size_t

BATCH_SIZE: Final = 1

AUTOFILL_SECONDS: Final = 8
MAX_SECONDS: Final = 10

SAMPLE_RATE: Final = 16000  # 16Khz
_MAX_SAMPLES: Final = MAX_SECONDS * SAMPLE_RATE

SAMPLES_PER_CHUNK: Final = 1280  # 80 ms @ 16Khz
MS_PER_CHUNK: Final = SAMPLES_PER_CHUNK // SAMPLE_RATE

# window = 400, hop length = 160
MELS_PER_SECOND: Final = 97
MAX_MELS: Final = MAX_SECONDS * MELS_PER_SECOND
MEL_SAMPLES: Final = 1760
NUM_MELS: Final = 32

EMB_FEATURES: Final = 76  # 775 ms
EMB_STEP: Final = 8
MAX_EMB: Final = MAX_SECONDS * EMB_STEP
WW_FEATURES: Final = 96

MEL_SHAPE: Final = (BATCH_SIZE, MEL_SAMPLES)
EMB_SHAPE: Final = (BATCH_SIZE, EMB_FEATURES, NUM_MELS, 1)

# melspec = [batch x samples (min: 1280)] => [batch x 1 x window x mels (32)]
# stft window size: 25ms (400)
# stft window step: 10ms (160)
# mel band limits: 60Hz - 3800Hz
# mel frequency bins: 32
#
# embedding = [batch x window x mels (32) x 1] => [batch x 1 x 1 x features (96)]
# ww = [batch x window x features (96)] => [batch x probability]


class OpenWakeWord(TfLiteWakeWord):
    def __init__(
        self,
        id: str,  # pylint: disable=redefined-builtin
        *,
        tflite_model: Union[str, Path],
        libtensorflowlite_c_path: Union[str, Path],
    ):
        TfLiteWakeWord.__init__(self, libtensorflowlite_c_path)

        self.id = id
        self.tflite_model = Path(tflite_model).resolve()

        # Load the model and create interpreter
        self.model_path = str(self.tflite_model).encode("utf-8")
        self.model = self.lib.TfLiteModelCreateFromFile(self.model_path)
        self.interpreter = self.lib.TfLiteInterpreterCreate(self.model, None)
        self.lib.TfLiteInterpreterAllocateTensors(self.interpreter)

        self.input_tensor = self.lib.TfLiteInterpreterGetInputTensor(
            self.interpreter, c_int32(0)
        )
        self.output_tensor = self.lib.TfLiteInterpreterGetOutputTensor(
            self.interpreter, c_int32(0)
        )

        num_input_dims = self.lib.TfLiteTensorNumDims(self.input_tensor)
        input_shape = [
            self.lib.TfLiteTensorDim(self.input_tensor, i)
            for i in range(num_input_dims)
        ]
        self.input_windows = input_shape[1]

        self.new_embeddings: int = 0
        self.embeddings: np.ndarray = np.zeros(
            shape=(MAX_EMB, WW_FEATURES), dtype=np.float32
        )

    def process_streaming(self, embeddings: np.ndarray) -> Iterable[float]:
        """Generate probabilities from embeddings."""
        if (not self.interpreter) or (not self.model):
            return

        num_embedding_windows = embeddings.shape[2]

        # Shift
        self.embeddings[:-num_embedding_windows] = self.embeddings[
            num_embedding_windows:
        ]

        # Overwrite
        self.embeddings[-num_embedding_windows:] = embeddings[0, 0, :, :]
        self.new_embeddings = min(
            len(self.embeddings),
            self.new_embeddings + num_embedding_windows,
        )

        while self.new_embeddings >= self.input_windows:
            emb_tensor = np.zeros(
                shape=(1, self.input_windows, WW_FEATURES),
                dtype=np.float32,
            )

            emb_tensor[0, :] = self.embeddings[
                -self.new_embeddings : len(self.embeddings)
                - self.new_embeddings
                + self.input_windows
            ]
            self.new_embeddings = max(0, self.new_embeddings - 1)

            # Run inference
            emb_ptr = emb_tensor.ctypes.data_as(c_void_p)
            self.lib.TfLiteTensorCopyFromBuffer(
                self.input_tensor, emb_ptr, c_size_t(emb_tensor.nbytes)
            )
            self.lib.TfLiteInterpreterInvoke(self.interpreter)

            output_bytes = self.lib.TfLiteTensorByteSize(self.output_tensor)
            probs = np.empty(
                output_bytes // np.dtype(np.float32).itemsize, dtype=np.float32
            )
            self.lib.TfLiteTensorCopyToBuffer(
                self.output_tensor,
                probs.ctypes.data_as(c_void_p),
                c_size_t(output_bytes),
            )

            yield probs.item()

    def reset(self) -> None:
        self.new_embeddings = 0
        self.embeddings = np.zeros(shape=(MAX_EMB, WW_FEATURES), dtype=np.float32)

    @staticmethod
    def from_model(
        model_path: Union[str, Path],
        libtensorflowlite_c_path: Optional[Union[str, Path]] = None,
    ) -> "OpenWakeWord":

        if libtensorflowlite_c_path is None:
            libtensorflowlite_c_path = _find_tensorflowlite_c()

        model_path = Path(model_path)

        return OpenWakeWord(
            id=model_path.stem,
            tflite_model=model_path,
            libtensorflowlite_c_path=libtensorflowlite_c_path,
        )

    @staticmethod
    def from_builtin(
        model: Model,
        models_dir: Union[str, Path] = _MODELS_DIR,
        libtensorflowlite_c_path: Optional[Union[str, Path]] = None,
    ) -> "OpenWakeWord":
        models_dir = Path(models_dir)

        return OpenWakeWord.from_model(
            models_dir / f"{model.value}.tflite",
            libtensorflowlite_c_path=libtensorflowlite_c_path,
        )

    def close(self) -> None:
        """Release resources."""
        if self.interpreter:
            self.lib.TfLiteInterpreterDelete(self.interpreter)
            self.interpreter = None

        if self.model:
            self.lib.TfLiteModelDelete(self.model)
            self.model = None

    def __del__(self) -> None:
        self.close()


# -----------------------------------------------------------------------------


class OpenWakeWordFeatures(TfLiteWakeWord):
    def __init__(
        self,
        melspectrogram_model: Union[str, Path],
        embedding_model: Union[str, Path],
        libtensorflowlite_c_path: Union[str, Path],
    ) -> None:
        TfLiteWakeWord.__init__(self, libtensorflowlite_c_path)

        self.mel_path = Path(melspectrogram_model).resolve()
        self.emb_path = Path(embedding_model).resolve()

        # Melspectrogram
        self.mel_model = self.lib.TfLiteModelCreateFromFile(
            str(self.mel_path).encode("utf-8")
        )
        self.mel_interpreter = self.lib.TfLiteInterpreterCreate(self.mel_model, None)

        mels_dims = (c_int32 * len(MEL_SHAPE))(*MEL_SHAPE)
        self.lib.TfLiteInterpreterResizeInputTensor(
            self.mel_interpreter,
            c_int32(0),
            mels_dims,
            c_int32(len(MEL_SHAPE)),
        )
        self.lib.TfLiteInterpreterAllocateTensors(self.mel_interpreter)
        self.mel_input_tensor = self.lib.TfLiteInterpreterGetInputTensor(
            self.mel_interpreter, c_int32(0)
        )
        self.mel_output_tensor = self.lib.TfLiteInterpreterGetOutputTensor(
            self.mel_interpreter, c_int32(0)
        )

        # Embedding
        self.emb_model = self.lib.TfLiteModelCreateFromFile(
            str(self.emb_path).encode("utf-8")
        )
        self.emb_interpreter = self.lib.TfLiteInterpreterCreate(self.emb_model, None)
        emb_dims = (c_int32 * len(EMB_SHAPE))(*EMB_SHAPE)
        self.lib.TfLiteInterpreterResizeInputTensor(
            self.emb_interpreter,
            c_int32(0),
            emb_dims,
            c_int32(len(EMB_SHAPE)),
        )
        self.lib.TfLiteInterpreterAllocateTensors(self.emb_interpreter)
        self.emb_input_tensor = self.lib.TfLiteInterpreterGetInputTensor(
            self.emb_interpreter, c_int32(0)
        )
        self.emb_output_tensor = self.lib.TfLiteInterpreterGetOutputTensor(
            self.emb_interpreter, c_int32(0)
        )

        # State
        self.new_audio_samples: int = AUTOFILL_SECONDS * SAMPLE_RATE
        self.audio: np.ndarray = np.zeros(shape=(_MAX_SAMPLES,), dtype=np.float32)
        self.new_mels: int = 0
        self.mels: np.ndarray = np.zeros(shape=(MAX_MELS, NUM_MELS), dtype=np.float32)

    def process_streaming(self, audio_chunk: bytes) -> Iterable[np.ndarray]:
        """Generate embeddings from audio."""
        if (
            (not self.mel_interpreter)
            or (not self.mel_model)
            or (not self.emb_interpreter)
            or (not self.emb_model)
        ):
            return

        chunk_array = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)

        # print(f"DEBUG: chunk_array len={len(chunk_array)}, self.audio len={len(self.audio)}")

        if len(chunk_array) == 0:
            return

        if len(chunk_array) >= len(self.audio):
            # print(f"DEBUG: Taking IF branch (large chunk)")
            self.audio[:] = chunk_array[-len(self.audio):]
            self.new_audio_samples = len(self.audio)
        else:
            # Shift samples left
            # print(f"DEBUG: Taking ELSE branch (normal chunk)")
            self.audio[: -len(chunk_array)] = self.audio[len(chunk_array) :]

            # Add new samples to end
            self.audio[-len(chunk_array) :] = chunk_array
            self.new_audio_samples = min(
                len(self.audio),
                self.new_audio_samples + len(chunk_array),
            )

        while self.new_audio_samples >= MEL_SAMPLES:
            audio_tensor = np.zeros(shape=(BATCH_SIZE, MEL_SAMPLES), dtype=np.float32)
            audio_tensor[0, :] = self.audio[
                -self.new_audio_samples : len(self.audio)
                - self.new_audio_samples
                + MEL_SAMPLES
            ]
            audio_tensor = np.ascontiguousarray(audio_tensor)
            self.new_audio_samples = max(0, self.new_audio_samples - SAMPLES_PER_CHUNK)

            # Run inference (mels)
            audio_ptr = audio_tensor.ctypes.data_as(c_void_p)
            self.lib.TfLiteTensorCopyFromBuffer(
                self.mel_input_tensor, audio_ptr, c_size_t(audio_tensor.nbytes)
            )
            self.lib.TfLiteInterpreterInvoke(self.mel_interpreter)

            mels_output_bytes = self.lib.TfLiteTensorByteSize(self.mel_output_tensor)
            mels = np.empty(
                mels_output_bytes // np.dtype(np.float32).itemsize, dtype=np.float32
            )
            self.lib.TfLiteTensorCopyToBuffer(
                self.mel_output_tensor,
                mels.ctypes.data_as(c_void_p),
                c_size_t(mels_output_bytes),
            )

            mels = (mels / 10) + 2  # transform to fit embedding
            mels = mels.reshape((1, 1, -1, NUM_MELS))

            # Shift left
            num_mel_windows = mels.shape[2]
            self.mels[:-num_mel_windows] = self.mels[num_mel_windows:]

            # Overwrite
            self.mels[-num_mel_windows:] = mels[0, 0, :, :]
            self.new_mels = min(len(self.mels), self.new_mels + num_mel_windows)

            while self.new_mels >= EMB_FEATURES:
                mels_tensor = np.ascontiguousarray(
                    np.zeros(shape=EMB_SHAPE, dtype=np.float32)
                )
                mels_tensor[0, :, :, 0] = self.mels[
                    -self.new_mels : len(self.mels) - self.new_mels + EMB_FEATURES, :
                ]
                self.new_mels = max(0, self.new_mels - EMB_STEP)

                # Run inference (embedding)
                mels_ptr = mels_tensor.ctypes.data_as(c_void_p)
                self.lib.TfLiteTensorCopyFromBuffer(
                    self.emb_input_tensor, mels_ptr, c_size_t(mels_tensor.nbytes)
                )
                self.lib.TfLiteInterpreterInvoke(self.emb_interpreter)

                emb_output_bytes = self.lib.TfLiteTensorByteSize(self.emb_output_tensor)
                emb = np.empty(
                    emb_output_bytes // np.dtype(np.float32).itemsize, dtype=np.float32
                )
                self.lib.TfLiteTensorCopyToBuffer(
                    self.emb_output_tensor,
                    emb.ctypes.data_as(c_void_p),
                    c_size_t(emb_output_bytes),
                )
                emb = emb.reshape((1, 1, -1, WW_FEATURES))
                yield emb

    def reset(self) -> None:
        self.new_audio_samples = AUTOFILL_SECONDS * SAMPLE_RATE
        self.audio = np.zeros(shape=(_MAX_SAMPLES,), dtype=np.float32)
        self.new_mels = 0
        self.mels = np.zeros(shape=(MAX_MELS, NUM_MELS), dtype=np.float32)

    @staticmethod
    def from_builtin(
        models_dir: Union[str, Path] = _MODELS_DIR,
        libtensorflowlite_c_path: Optional[Union[str, Path]] = None,
    ) -> "OpenWakeWordFeatures":
        models_dir = Path(models_dir)

        if libtensorflowlite_c_path is None:
            libtensorflowlite_c_path = _find_tensorflowlite_c()

        return OpenWakeWordFeatures(
            melspectrogram_model=models_dir / "melspectrogram.tflite",
            embedding_model=models_dir / "embedding_model.tflite",
            libtensorflowlite_c_path=libtensorflowlite_c_path,
        )

    def close(self) -> None:
        """Release resources."""
        if self.mel_interpreter:
            self.lib.TfLiteInterpreterDelete(self.mel_interpreter)
            self.mel_interpreter = None

        if self.mel_model:
            self.lib.TfLiteModelDelete(self.mel_model)
            self.mel_model = None

        if self.emb_interpreter:
            self.lib.TfLiteInterpreterDelete(self.emb_interpreter)
            self.emb_interpreter = None

        if self.emb_model:
            self.lib.TfLiteModelDelete(self.emb_model)
            self.emb_model = None

    def __del__(self) -> None:
        self.close()


# -----------------------------------------------------------------------------


def _find_tensorflowlite_c() -> Path:
    # Try module lib dir first (inside wheel)
    libtensorflowlite_c_path = next(
        iter(_MODULE_LIB_DIR.glob("*tensorflowlite_c.*")), None
    )

    if not libtensorflowlite_c_path:
        # Try repo dir
        platform = get_platform()
        if not platform:
            raise ValueError("Unable to detect platform for tensorflowlite_c")

        lib_dir = _REPO_LIB_DIR / platform
        libtensorflowlite_c_path = next(iter(lib_dir.glob("*tensorflowlite_c.*")), None)

    if not libtensorflowlite_c_path:
        raise ValueError("Failed to find tensorflowlite_c library")

    return libtensorflowlite_c_path
