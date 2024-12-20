import Preprocessing.full_prep_pipeline as prepare
import DP_OOPPM.train_model as train_model

import pandas as pd
from sklearn.metrics import roc_auc_score
from itertools import product
import logging
import torch

import os


# Main hyperparameter tuning function
def run_hyper(dataset_name, logname, max_prefix_len, addendum):
    """
    Runs hyperparameter tuning for an LSTM model on a specified dataset.

    This function sets up logging, prepares the data, generates combinations of 
    hyperparameters, and iterates over them to train and evaluate models. It logs 
    the AUC scores for each combination and saves the results to a CSV file. 
    Previously completed combinations are skipped to avoid redundant computations.

    Parameters:
        dataset_name (str): Path to the dataset file.
        logname (str): Type of log for determining preprocessing steps.
        max_prefix_len (int): Maximum length of prefixes to generate.
        addendum (str): Additional identifier for the results file.

    Returns:
        pd.DataFrame: A DataFrame containing the results of the hyperparameter tuning.
    """
    # Log setup
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Data Preparation
    X_train, seq_len_train, y_train, s_train, X_val, seq_len_val, y_val, s_val, _, _, _, _, vocsizes, num_numerical_features, new_max_prefix_len = prepare.full_prep(filename=dataset_name, logname=logname, 
                                                                                                                                                                                       max_prefix_len=max_prefix_len, drop_sensitive=False, 
                                                                                                                                                                                       sensitive_column='case:gender')
    
    # Hyperparameter grids
    num_layers_lst = [1, 2]
    bidirectional_lst = [False, True]
    LSTM_size_lst = [16, 32, 64]
    batch_size_lst = [128, 256, 512] #we need a large size anyway later
    learning_rate_lst = [0.0001, 0.001]
    dropout_lst = [0.2, 0.4]


    # Generate all combinations of hyperparameters
    hyperparameter_combinations = list(product(num_layers_lst, bidirectional_lst, LSTM_size_lst, batch_size_lst, 
                                               learning_rate_lst, dropout_lst))
    
    # Check for existing results file
    results_path = f"Results/Hyperparameters/BCE/{logname}_{addendum}_hyperparameter_tuning_results.csv"
    if os.path.exists(results_path):
        # Load existing results
        existing_results_df = pd.read_csv(results_path)
        # Extract completed hyperparameter combinations to skip
        completed_combinations = set(
            tuple(row) for row in existing_results_df[['num_layers', 'bidirectional', 'lstm_size', 
                                                       'batch_size', 'learning_rate', 'dropout']].itertuples(index=False, name=None)
        )
    else:
        # Initialize an empty DataFrame if results file doesn't exist
        existing_results_df = pd.DataFrame(columns=['num_layers', 'bidirectional', 'lstm_size', 'batch_size', 
                                                    'learning_rate', 'dropout', 'auc_score'])
        completed_combinations = set()
    
    # List to store new results
    new_results = []

    # Filter out completed combinations
    combinations_to_run = [comb for comb in hyperparameter_combinations if comb not in completed_combinations]

    for combination in combinations_to_run:
        num_layers, bidirectional, lstm_size, batch_size, learning_rate, dropout = combination
        
        logging.info(f"Training with hyperparameters: {combination}")

        # Initialize and train the model
        #we decreased the patience a bit, since e are just interested in best setup
        model = initialize_model(
            X_train=X_train, 
            seq_len_train=seq_len_train, 
            y_train=y_train, 
            s_train=s_train, 
            vocab_sizes=vocsizes, 
            num_numerical_features=num_numerical_features, 
            num_layers=num_layers, 
            bidirectional=bidirectional, 
            lstm_size=lstm_size, 
            batch_size=batch_size, 
            learning_rate=learning_rate, 
            dropout=dropout, 
            max_length=new_max_prefix_len,
            max_epochs=300, 
            patience=20, 
            X_val=X_val, 
            seq_len_val=seq_len_val, 
            y_val=y_val, 
            s_val=s_val
        )
        
        # Evaluate the model
        auc = evaluate_model(model, X_val, y_val, seq_len_val)
        
        # Log results
        logging.info(f"AUC for {combination}: {auc}")
        
        # Save hyperparameters and AUC to new_results list
        new_results.append({
            'num_layers': num_layers,
            'bidirectional': bidirectional,
            'lstm_size': lstm_size,
            'batch_size': batch_size,
            'learning_rate': learning_rate,
            'dropout': dropout,
            'auc_score': auc
        })

        # Save intermediate results to CSV after each iteration
        temp_results_df = pd.DataFrame(new_results)
        results_df = pd.concat([existing_results_df, temp_results_df], ignore_index=True)
        results_df.to_csv(results_path, index=False)

    # Final save of all results to CSV
    results_df = pd.concat([existing_results_df, pd.DataFrame(new_results)], ignore_index=True)
    results_df.to_csv(results_path, index=False)
    
    # Return the final results DataFrame (optional)
    return results_df

def initialize_model(X_train, seq_len_train, y_train, s_train, vocab_sizes, num_numerical_features, 
                     num_layers, bidirectional, lstm_size, batch_size, learning_rate, dropout, 
                     max_length, max_epochs, patience, X_val, seq_len_val, y_val, s_val):
    #Initializes and trains an LSTM model using the specified training and validation data.
    model = train_model.train_and_return_LSTM(
        X_train=X_train, 
        seq_len_train=seq_len_train, 
        y_train=y_train, 
        s_train=s_train, 
        loss_function='BCE', 
        vocab_sizes=vocab_sizes, 
        num_numerical_features=num_numerical_features, 
        dropout=dropout, 
        lstm_size=lstm_size, 
        num_lstm=num_layers, 
        bidirectional=bidirectional, 
        max_length=max_length, 
        learning_rate=learning_rate, 
        max_epochs=max_epochs, 
        batch_size=batch_size, 
        patience=patience, 
        get_history=False, 
        X_val=X_val, 
        seq_len_val=seq_len_val, 
        y_val=y_val, 
        s_val=s_val
    )
    return model

def evaluate_model(model, X_val, y_val, seq_len_val):
    """
    Evaluates the performance of a given model on validation data using the AUC metric.

    This function moves the model and validation data to the appropriate device (GPU if available),
    performs a forward pass to obtain predictions, and computes the AUC score based on the ground
    truth and predicted values.

    Parameters:
        model (torch.nn.Module): The model to be evaluated.
        X_val (torch.Tensor): Validation input data.
        y_val (torch.Tensor): Ground truth labels for the validation data.
        seq_len_val (torch.Tensor): Sequence lengths for the validation data.

    Returns:
        float: The AUC score of the model on the validation data.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    X_val, seq_len_val = X_val.to(device), seq_len_val.to(device)

    val_output = model(X_val, seq_len_val)
    val_np = val_output.detach().cpu().numpy()

    # Get the ground truth and predictions
    y_gt = y_val.numpy().ravel()
    y_pred = val_np.ravel()

    # Compute AUC score
    auc = roc_auc_score(y_gt, y_pred)
    return auc


run_hyper('Datasets/lending_log_high.xes.gz', 'lending', 6, 'high')

run_hyper('Datasets/lending_log_medium.xes.gz', 'lending', 6, 'medium')

run_hyper('Datasets/lending_log_low.xes.gz', 'lending', 6, 'low')


run_hyper('Datasets/hiring_log_high.xes.gz', 'hiring', 6, 'high')

run_hyper('Datasets/hiring_log_medium.xes.gz', 'hiring', 6, 'medium')

run_hyper('Datasets/hiring_log_low.xes.gz', 'hiring', 6, 'low')


run_hyper('Datasets/renting_log_high.xes.gz', 'renting', 6, 'high')

run_hyper('Datasets/renting_log_medium.xes.gz', 'renting', 6, 'medium')

run_hyper('Datasets/renting_log_low.xes.gz', 'renting', 6, 'low')

