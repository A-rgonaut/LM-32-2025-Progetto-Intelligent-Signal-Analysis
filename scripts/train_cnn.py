import os
import torch
import numpy as np
import pandas as pd
import torch.nn as nn
import torch.optim as optim
from dotenv import load_dotenv
from comet_ml import Experiment
from torch.utils.data import DataLoader
from src.data import AudioDepressionDataset
from src.models import CNNMLP
from src.training import (
    train_epoch_binary, 
    eval_model_binary, 
    EarlyStopping, 
    load_labels_from_dataset, 
    get_audio_paths,    
    print_model_summary
)

def main():
    # --- 1. CONFIGURAZIONE DELL'ESPERIMENTO ---
    print("--- Configurazione dell'esperimento CNN ---")
    SEED = 42
    DATASET_NAME = "datasets/DAIC-WOZ-Cleaned"
    MODEL_SAVE_PATH = "cnn_best.pth"
    
    load_dotenv()
    experiment = Experiment(
        api_key=os.getenv("COMET_API_KEY"),
        project_name=os.getenv("COMET_PROJECT_NAME"),
        workspace=os.getenv("COMET_WORKSPACE")
    )

    # Iperparametri
    BATCH_SIZE = 512
    LEARNING_RATE = 0.01
    NUM_EPOCHS = 100
    NUM_WORKERS = os.cpu_count() // 2 if os.cpu_count() > 1 else 0

    # Impostazione del seed per la riproducibilità
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    
    # Selezione del device
    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    print(f"Using device: {device}")

    # --- 2. CARICAMENTO E PREPARAZIONE DEI DATI ---
    print("\n--- Caricamento dati ---")
    train_df = pd.read_csv(os.path.join(DATASET_NAME, 'train_split_Depression_AVEC2017.csv'))
    dev_df = pd.read_csv(os.path.join(DATASET_NAME, 'dev_split_Depression_AVEC2017.csv'))

    y_train = load_labels_from_dataset(train_df)
    y_dev = load_labels_from_dataset(dev_df) 

    train_paths = get_audio_paths(train_df, DATASET_NAME)
    dev_paths = get_audio_paths(dev_df, DATASET_NAME)

    # Creazione dei Dataset
    train_dataset = AudioDepressionDataset(audio_paths=train_paths, labels=y_train)
    dev_dataset = AudioDepressionDataset(audio_paths=dev_paths, labels=y_dev)

    # Creazione dei DataLoader
    train_dataloader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS)
    dev_dataloader = DataLoader(dev_dataset, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS)
    print(f"Train segments: {len(train_dataset)}, Dev segments: {len(dev_dataset)}")

    # --- 3. INIZIALIZZAZIONE MODELLO E COMPONENTI DI TRAINING ---
    print("\n--- Inizializzazione modello ---")
    model = CNNMLP().to(device)
    print_model_summary(model)
    optimizer = optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=LEARNING_RATE)
    scheduler = None
    criterion = nn.BCELoss()
    early_stopping = EarlyStopping(patience=5, min_delta=0.005, mode='max') 
    experiment.set_model_graph(model)
    
    # --- 4. TRAINING LOOP ---
    print("\n--- Inizio Training ---")
    best_val_f1 = -1.0

    for epoch in range(NUM_EPOCHS):
        # Training
        train_loss, train_acc = train_epoch_binary(model, train_dataloader, criterion, optimizer, scheduler, device, epoch, NUM_EPOCHS)
        experiment.log_metric("train/loss", train_loss, step=epoch)
        experiment.log_metric("train/accuracy", train_acc, step=epoch)
        # Validation
        val_loss, val_acc, val_f1 = eval_model_binary(model, dev_dataloader, criterion, device)
        print(f"Epoch {epoch+1:02d} | Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.4f} | Val Loss: {val_loss:.4f} | Val Acc: {val_acc:.4f} | Val F1: {val_f1:.4f}")
        experiment.log_metric("val/loss", val_loss, step=epoch)
        experiment.log_metric("val/accuracy", val_acc, step=epoch)
        experiment.log_metric("val/f1", val_f1, step=epoch)
        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            torch.save(model.state_dict(), MODEL_SAVE_PATH)
            print(f"-> Nuovo miglior F1-score: {best_val_f1:.4f}. Modello salvato in '{MODEL_SAVE_PATH}'")

        if early_stopping(val_f1):
            print(f"Early stopping attivato dopo {epoch+1} epoche.")
            break       

    print("\n--- Training Completato ---")

if __name__ == '__main__':
    main()