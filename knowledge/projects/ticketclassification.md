# Ticket Classification

Role:
Data Scientist at LinkedIn

Problem:
When an engeneer submited a ticket, we needed a fast way to route it to the correct team for resolution. There was already an existing solution for that but it was not very accurate and was not able to handle the growing amount of tickets. 

My contributions:
- Data cleaning and normalization (Ticket Title, Description text)
- regular training and retraining of the model, testing it, deployment to stage and production.
- Owning the model in prodacton and improving it based on misclassifications analysis.
- leding misclassification analitics and iterating on model improvements based on them.
- mentoring another engineer to take over the model.
- working on taxanomy
- model evaluation
- Production monitoring
- Working on model explainability and identifying root causes of misclassifications.
- creating graphana dashboards for monitoring of the model.
- model evaluation: evaluation was a core part of development. I maintained separate training, validation, and test datasets and tracked classification metrics including accuracy, precision, recall, and confusion matrices. I regularly analyzed misclassified tickets to identify labeling issues and emerging patterns. Those insights fed back into data collection and model retraining. In production, we monitored prediction distributions and business metrics to detect model drift and performance degradation over time.

Technologies:
FastText
scikit-learn
Graphana
SQL
Python
FastAPI